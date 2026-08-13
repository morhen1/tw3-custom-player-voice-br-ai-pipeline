#!/usr/bin/env python3
"""Audita artefatos acústicos em um lote de WAVs brutos e pós-processados.

A análise é local e heurística. Ela procura pausas internas excessivas, pequenos
fragmentos isolados, som ativo perto do fim, clipping e fala globalmente rápida.
O relatório serve para priorizar revisão humana; não substitui uma escuta final.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - validado ao iniciar a CLI
    raise SystemExit("ERRO: a auditoria requer numpy no mesmo Python") from exc


class AuditError(RuntimeError):
    pass


ID_RE = re.compile(r"^0x[0-9a-f]{8}$")
LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ]+)?")
VOWEL_GROUP_RE = re.compile(r"[aeiouáàâãéêíóôõúü]+", re.IGNORECASE)
INTERNAL_PUNCT_RE = re.compile(r"(?:\.\.\.|[,;:—–-])")


@dataclass(frozen=True)
class AudioMetrics:
    duration_s: float
    sample_rate: int
    channels: int
    peak_dbfs: float
    rms_dbfs: float
    threshold_dbfs: float
    trim_start_s: float
    trim_end_s: float
    trimmed_duration_s: float
    active_duration_s: float
    active_ratio: float
    internal_pause_count: int
    micro_pause_count: int
    long_pause_count: int
    max_internal_pause_ms: float
    pause_duration_ms: float
    active_run_count: int
    internal_blip_count: int
    shortest_internal_blip_ms: float
    tail_margin_ms: float
    tail_island_ms: float
    tail_gap_ms: float
    clipping_ratio: float
    max_step_ratio: float


@dataclass(frozen=True)
class Item:
    ident: str
    text: str
    original_duration_s: float
    raw_path: Path
    final_path: Path
    processing_speed: float


def normalize_id(value: str) -> str:
    ident = value.strip().lower()
    if not ID_RE.fullmatch(ident):
        raise AuditError(f"ID inválido: {value}")
    return ident


def dbfs(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def _decode_pcm(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 3:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        values = (
            packed[:, 0].astype(np.int32)
            | (packed[:, 1].astype(np.int32) << 8)
            | (packed[:, 2].astype(np.int32) << 16)
        )
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float32) / 8388608.0
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    raise AuditError(f"PCM com largura não suportada: {sample_width * 8} bits")


def _runs(mask: np.ndarray, state: bool) -> list[tuple[int, int]]:
    selected = np.asarray(mask, dtype=bool)
    if not state:
        selected = ~selected
    padded = np.pad(selected.astype(np.int8), (1, 1))
    changes = np.diff(padded)
    starts = np.flatnonzero(changes == 1)
    ends = np.flatnonzero(changes == -1)
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


def _bridge_tiny_silences(active: np.ndarray, maximum_frames: int = 2) -> np.ndarray:
    result = active.copy()
    for start, end in _runs(result, False):
        if start > 0 and end < result.size and end - start <= maximum_frames:
            result[start:end] = True
    return result


def analyze_wav(path: Path, frame_ms: float = 10.0) -> AudioMetrics:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_width = handle.getsampwidth()
            frame_count = handle.getnframes()
            compression = handle.getcomptype()
            payload = handle.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise AuditError(f"não foi possível abrir {path}: {exc}") from exc
    if compression != "NONE":
        raise AuditError(f"WAV comprimido não suportado: {path} ({compression})")
    if channels < 1 or sample_rate < 8000 or frame_count < 1:
        raise AuditError(f"WAV inválido: {path}")

    samples = _decode_pcm(payload, sample_width)
    if samples.size % channels:
        raise AuditError(f"WAV com amostras incompletas: {path}")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)
    samples = np.nan_to_num(samples.astype(np.float32, copy=False))
    duration_s = float(samples.size / sample_rate)
    absolute = np.abs(samples)
    peak = float(np.max(absolute)) if samples.size else 0.0
    overall_rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))

    frame_samples = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    frame_count_energy = int(math.ceil(samples.size / frame_samples))
    padding = frame_count_energy * frame_samples - samples.size
    framed = np.pad(samples, (0, padding)).reshape(frame_count_energy, frame_samples)
    energy = np.sqrt(np.mean(framed.astype(np.float64) ** 2, axis=1))
    energy_db = 20.0 * np.log10(np.maximum(energy, 1e-12))
    p90 = float(np.percentile(energy_db, 90))
    threshold = max(-50.0, min(-36.0, p90 - 32.0))
    active = _bridge_tiny_silences(energy_db > threshold, maximum_frames=2)

    active_indexes = np.flatnonzero(active)
    if active_indexes.size == 0:
        raise AuditError(f"áudio vazio ou silencioso: {path}")
    first = int(active_indexes[0])
    last = int(active_indexes[-1])
    trim_start_s = first * frame_ms / 1000.0
    trim_end_s = min(duration_s, (last + 1) * frame_ms / 1000.0)
    trimmed_duration_s = max(0.0, trim_end_s - trim_start_s)

    internal = active[first : last + 1]
    silence_runs = [
        (start, end)
        for start, end in _runs(internal, False)
        if start > 0 and end < internal.size
    ]
    silence_ms = [(end - start) * frame_ms for start, end in silence_runs]
    pauses = [duration for duration in silence_ms if duration >= 35.0]
    micro_pauses = [duration for duration in pauses if duration <= 180.0]
    long_pauses = [duration for duration in pauses if duration > 180.0]

    active_runs = _runs(internal, True)
    internal_blips: list[float] = []
    for index, (start, end) in enumerate(active_runs):
        if index == 0 or index == len(active_runs) - 1:
            continue
        duration = (end - start) * frame_ms
        left_gap = (start - active_runs[index - 1][1]) * frame_ms
        right_gap = (active_runs[index + 1][0] - end) * frame_ms
        if duration <= 90.0 and left_gap >= 35.0 and right_gap >= 35.0:
            internal_blips.append(duration)

    tail_island_ms = 0.0
    tail_gap_ms = 0.0
    if len(active_runs) >= 2:
        tail_start, tail_end = active_runs[-1]
        previous_end = active_runs[-2][1]
        candidate_island = (tail_end - tail_start) * frame_ms
        candidate_gap = (tail_start - previous_end) * frame_ms
        relative_start = tail_start / max(1, internal.size)
        if candidate_island <= 220.0 and candidate_gap >= 40.0 and relative_start >= 0.60:
            tail_island_ms = candidate_island
            tail_gap_ms = candidate_gap

    tail_margin_ms = max(0.0, (duration_s - trim_end_s) * 1000.0)
    active_duration_s = float(np.sum(active) * frame_ms / 1000.0)
    clipping_ratio = float(np.mean(absolute >= 0.999)) if absolute.size else 0.0
    differences = np.abs(np.diff(samples))
    max_step = float(np.max(differences)) if differences.size else 0.0
    max_step_ratio = max_step / max(overall_rms, 1e-8)

    return AudioMetrics(
        duration_s=duration_s,
        sample_rate=sample_rate,
        channels=channels,
        peak_dbfs=dbfs(peak),
        rms_dbfs=dbfs(overall_rms),
        threshold_dbfs=threshold,
        trim_start_s=trim_start_s,
        trim_end_s=trim_end_s,
        trimmed_duration_s=trimmed_duration_s,
        active_duration_s=active_duration_s,
        active_ratio=active_duration_s / max(duration_s, 1e-9),
        internal_pause_count=len(pauses),
        micro_pause_count=len(micro_pauses),
        long_pause_count=len(long_pauses),
        max_internal_pause_ms=max(pauses, default=0.0),
        pause_duration_ms=sum(pauses),
        active_run_count=len(active_runs),
        internal_blip_count=len(internal_blips),
        shortest_internal_blip_ms=min(internal_blips, default=0.0),
        tail_margin_ms=tail_margin_ms,
        tail_island_ms=tail_island_ms,
        tail_gap_ms=tail_gap_ms,
        clipping_ratio=clipping_ratio,
        max_step_ratio=max_step_ratio,
    )


def text_metrics(text: str) -> dict[str, int]:
    letters = len(LETTER_RE.findall(text))
    words = len(WORD_RE.findall(text))
    syllables = max(words, len(VOWEL_GROUP_RE.findall(text)))
    without_terminal = re.sub(r"[.!?…\s]+$", "", text)
    punctuation = len(INTERNAL_PUNCT_RE.findall(without_terminal))
    return {
        "letters": letters,
        "words": words,
        "syllables": syllables,
        "internal_punctuation": punctuation,
    }


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise AuditError(f"manifesto não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows:
        raise AuditError(f"manifesto vazio: {path}")
    return rows


def read_processing_speeds(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    if not path.is_file():
        raise AuditError(f"relatório de processamento não encontrado: {path}")
    result: dict[str, float] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                ident = normalize_id(row.get("id_hex", ""))
                value = float(row.get("fator_velocidade", "") or 0.0)
            except (AuditError, ValueError):
                continue
            if value > 0:
                result[ident] = value
    return result


def read_selection_ids(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    if not path.is_file():
        raise AuditError(f"seleção JSONL não encontrada: {path}")
    selected: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
                ident = normalize_id(str(payload.get("id", "")))
            except (json.JSONDecodeError, AuditError) as exc:
                raise AuditError(
                    f"{path}, linha {line_number}: seleção inválida"
                ) from exc
            if ident in selected:
                raise AuditError(f"ID repetido na seleção: {ident}")
            selected.add(ident)
    if not selected:
        raise AuditError(f"seleção JSONL vazia: {path}")
    return selected


def read_baseline_populations(path: Path | None) -> dict[str, list[float]] | None:
    if path is None:
        return None
    if not path.is_file():
        raise AuditError(f"relatório-base não encontrado: {path}")
    columns = {
        "syllables_per_s": [],
        "letters_per_s": [],
        "pause_density": [],
        "raw_pause_density": [],
        "risk_score": [],
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            for name, values in columns.items():
                try:
                    values.append(float(row.get(name, "")))
                except (TypeError, ValueError):
                    pass
    if any(not values for values in columns.values()):
        raise AuditError(f"relatório-base incompleto: {path}")
    return columns


def build_items(
    manifest_rows: Iterable[dict[str, str]],
    raw_dir: Path,
    final_dir: Path,
    speeds: dict[str, float],
    selected_ids: set[str] | None = None,
) -> tuple[list[Item], list[dict[str, str]]]:
    items: list[Item] = []
    missing: list[dict[str, str]] = []
    for row in manifest_rows:
        if (row.get("acao") or "").strip().lower() != "gerar":
            continue
        ident = normalize_id(row.get("id_hex", ""))
        if selected_ids is not None and ident not in selected_ids:
            continue
        raw_path = raw_dir / f"{ident}.wav"
        final_path = final_dir / f"{ident}.wav"
        absent = []
        if not raw_path.is_file():
            absent.append("bruto")
        if not final_path.is_file():
            absent.append("final")
        if absent:
            missing.append({"id_hex": ident, "ausente": ",".join(absent)})
            continue
        try:
            original_duration = float(row.get("duracao_original", "") or 0.0)
        except ValueError:
            original_duration = 0.0
        text = (row.get("texto_final") or row.get("texto_original") or "").strip()
        items.append(
            Item(
                ident=ident,
                text=text,
                original_duration_s=original_duration,
                raw_path=raw_path,
                final_path=final_path,
                processing_speed=speeds.get(ident, 0.0),
            )
        )
    return items, missing


def analyze_item(item: Item) -> dict[str, object]:
    raw = analyze_wav(item.raw_path)
    final = analyze_wav(item.final_path)
    text = text_metrics(item.text)
    speech_time = max(
        0.08,
        final.trimmed_duration_s - final.pause_duration_ms / 1000.0,
    )
    raw_speech_time = max(
        0.08,
        raw.trimmed_duration_s - raw.pause_duration_ms / 1000.0,
    )
    effective_speed = raw_speech_time / speech_time
    return {
        "id_hex": item.ident,
        "texto": item.text,
        "duracao_original_s": item.original_duration_s,
        **text,
        "raw": raw,
        "final": final,
        "processing_speed": item.processing_speed,
        "effective_speed": effective_speed,
        "letters_per_s": text["letters"] / speech_time,
        "syllables_per_s": text["syllables"] / speech_time,
        "pause_density": final.micro_pause_count / max(final.trimmed_duration_s, 0.08),
        "raw_pause_density": raw.micro_pause_count / max(raw.trimmed_duration_s, 0.08),
    }


def percentile(values: Iterable[float], value: float) -> float:
    ordered = np.asarray(list(values), dtype=np.float64)
    if ordered.size == 0:
        return 0.0
    return float(np.mean(ordered <= value) * 100.0)


def score_rows(
    rows: list[dict[str, object]],
    baseline: dict[str, list[float]] | None = None,
) -> None:
    syllable_rates = (
        baseline["syllables_per_s"]
        if baseline
        else [float(row["syllables_per_s"]) for row in rows]
    )
    letter_rates = (
        baseline["letters_per_s"]
        if baseline
        else [float(row["letters_per_s"]) for row in rows]
    )
    pause_densities = (
        baseline["pause_density"]
        if baseline
        else [float(row["pause_density"]) for row in rows]
    )
    raw_pause_densities = (
        baseline["raw_pause_density"]
        if baseline
        else [float(row["raw_pause_density"]) for row in rows]
    )

    for row in rows:
        raw = row["raw"]
        final = row["final"]
        assert isinstance(raw, AudioMetrics)
        assert isinstance(final, AudioMetrics)
        punctuation = int(row["internal_punctuation"])
        reasons: list[str] = []
        score = 0

        pause_excess = max(0, raw.micro_pause_count - punctuation - 1)
        if pause_excess >= 3:
            score += 38
            reasons.append(f"pausas internas agrupadas ({raw.micro_pause_count})")
        elif pause_excess == 2:
            score += 24
            reasons.append(f"pausas internas possivelmente excessivas ({raw.micro_pause_count})")
        elif pause_excess == 1:
            score += 10

        if raw.internal_blip_count or final.internal_blip_count:
            score += 40
            reasons.append("fragmento curto isolado no meio")

        if final.tail_island_ms > 0:
            if final.tail_island_ms <= 100.0:
                score += 42
                reasons.append(
                    f"possível vazamento final ({final.tail_island_ms:.0f} ms após pausa)"
                )
            else:
                score += 16
                reasons.append(
                    f"segmento final isolado ({final.tail_island_ms:.0f} ms; conferir)"
                )
        if final.tail_margin_ms < 25.0:
            score += 30
            reasons.append(f"som muito perto do corte final ({final.tail_margin_ms:.0f} ms)")
        elif final.tail_margin_ms < 45.0:
            score += 12
            reasons.append(f"margem final curta ({final.tail_margin_ms:.0f} ms)")

        speed = max(float(row["processing_speed"]), float(row["effective_speed"]))
        if speed >= 1.18:
            score += 26
            reasons.append(f"aceleração forte ({speed:.2f}x)")
        elif speed >= 1.12:
            score += 14
            reasons.append(f"aceleração perceptível ({speed:.2f}x)")

        syllable_percentile = percentile(syllable_rates, float(row["syllables_per_s"]))
        letter_percentile = percentile(letter_rates, float(row["letters_per_s"]))
        pause_percentile = percentile(pause_densities, float(row["pause_density"]))
        raw_pause_percentile = percentile(
            raw_pause_densities, float(row["raw_pause_density"])
        )
        row["syllable_rate_percentile"] = syllable_percentile
        row["letter_rate_percentile"] = letter_percentile
        row["pause_density_percentile"] = pause_percentile
        row["raw_pause_density_percentile"] = raw_pause_percentile

        if syllable_percentile >= 99.5 and float(row["syllables_per_s"]) >= 7.0:
            score += 30
            reasons.append(f"fala muito rápida ({row['syllables_per_s']:.1f} sílabas/s estimadas)")
        elif syllable_percentile >= 97.5 and float(row["syllables_per_s"]) >= 6.5:
            score += 16
            reasons.append(f"fala rápida ({row['syllables_per_s']:.1f} sílabas/s estimadas)")
        elif letter_percentile >= 99.5 and float(row["letters_per_s"]) >= 18.0:
            score += 20
            reasons.append(f"densidade de texto muito alta ({row['letters_per_s']:.1f} letras/s)")

        if (
            raw_pause_percentile >= 99.0
            and raw.micro_pause_count >= punctuation + 2
        ):
            score += 20
            reasons.append("densidade de pausas entre as maiores do lote")
        elif pause_percentile >= 98.0 and final.micro_pause_count >= punctuation + 2:
            score += 12
            reasons.append("muitas pausas curtas no áudio final")

        if final.clipping_ratio >= 0.0005:
            score += 45
            reasons.append(f"clipping ({final.clipping_ratio * 100:.3f}% das amostras)")
        elif final.max_step_ratio >= 28.0:
            score += 18
            reasons.append("transiente abrupto; possível clique")

        delta_pct = (
            (final.duration_s / float(row["duracao_original_s"]) - 1.0) * 100.0
            if float(row["duracao_original_s"]) > 0
            else 0.0
        )
        row["delta_final_pct"] = delta_pct
        if abs(delta_pct) >= 40.0:
            score += 12
            reasons.append(f"duração muito diferente da original ({delta_pct:+.0f}%)")

        row["risk_score"] = score
        row["motivos"] = " | ".join(dict.fromkeys(reasons))

    # A fala sintética contém muitas oclusivas e pausas estilísticas que parecem
    # artefatos quando vistas isoladamente. Classificar pelo percentil combinado
    # mantém a triagem útil: os 5% mais suspeitos são separados em três níveis.
    risk_scores = (
        baseline["risk_score"]
        if baseline
        else [float(row["risk_score"]) for row in rows]
    )
    for row in rows:
        risk_percentile = percentile(risk_scores, float(row["risk_score"]))
        row["risk_percentile"] = risk_percentile
        hard_failure = False
        final = row["final"]
        assert isinstance(final, AudioMetrics)
        if final.clipping_ratio >= 0.0005:
            hard_failure = True
        if hard_failure or risk_percentile >= 99.0:
            priority = "alta"
        elif risk_percentile >= 97.5:
            priority = "media"
        elif risk_percentile >= 95.0:
            priority = "baixa"
        else:
            priority = "ok"
        row["prioridade"] = priority


def flatten_row(row: dict[str, object]) -> dict[str, object]:
    result = {key: value for key, value in row.items() if key not in {"raw", "final"}}
    raw = row["raw"]
    final = row["final"]
    assert isinstance(raw, AudioMetrics)
    assert isinstance(final, AudioMetrics)
    result.update({f"bruto_{key}": value for key, value in asdict(raw).items()})
    result.update({f"final_{key}": value for key, value in asdict(final).items()})
    return result


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise AuditError(f"nenhum registro para escrever em {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--final-dir", type=Path, required=True)
    parser.add_argument("--processing-report", type=Path)
    parser.add_argument(
        "--selection-jsonl",
        type=Path,
        help="limita a auditoria aos IDs presentes neste JSONL",
    )
    parser.add_argument(
        "--baseline-report",
        type=Path,
        help="usa as distribuições deste relatório completo para percentis e prioridades",
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-report", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--review-limit",
        type=int,
        default=1000,
        help="máximo de itens no relatório priorizado; 0 inclui todos os suspeitos",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.workers < 1:
            raise AuditError("--workers deve ser pelo menos 1")
        speeds = read_processing_speeds(args.processing_report)
        selected_ids = read_selection_ids(args.selection_jsonl)
        baseline = read_baseline_populations(args.baseline_report)
        items, missing = build_items(
            read_manifest(args.manifest),
            args.raw_dir,
            args.final_dir,
            speeds,
            selected_ids,
        )
        if selected_ids is not None:
            represented = {item.ident for item in items}
            absent_from_manifest = sorted(selected_ids - represented)
            if absent_from_manifest:
                raise AuditError(
                    f"{len(absent_from_manifest)} ID(s) selecionado(s) ausente(s) dos pares WAV/manifesto"
                )
        if not items:
            raise AuditError("nenhum par bruto/final encontrado")
        print(f"Pares encontrados: {len(items)}; ausentes: {len(missing)}; workers={args.workers}")

        rows: list[dict[str, object]] = []
        failures: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(analyze_item, item): item for item in items}
            for number, future in enumerate(as_completed(futures), start=1):
                item = futures[future]
                try:
                    rows.append(future.result())
                except Exception as exc:
                    failures.append({"id_hex": item.ident, "erro": str(exc)})
                if number == 1 or number % 500 == 0 or number == len(items):
                    print(f"Progresso: {number}/{len(items)}", flush=True)

        if not rows:
            raise AuditError("todos os áudios falharam na análise")
        score_rows(rows, baseline)
        rows.sort(key=lambda row: str(row["id_hex"]))
        full_rows = [flatten_row(row) for row in rows]
        write_csv(args.report, full_rows)

        suspicious = [row for row in rows if row["prioridade"] != "ok"]
        priority_order = {"alta": 0, "media": 1, "baixa": 2, "ok": 3}
        suspicious.sort(
            key=lambda row: (
                priority_order[str(row["prioridade"])],
                -int(row["risk_score"]),
                str(row["id_hex"]),
            )
        )
        selected = suspicious if args.review_limit == 0 else suspicious[: args.review_limit]
        if selected:
            write_csv(args.review_report, [flatten_row(row) for row in selected])
        else:
            args.review_report.parent.mkdir(parents=True, exist_ok=True)
            args.review_report.write_text("id_hex;prioridade;risk_score;motivos\n", encoding="utf-8-sig")

        counts = {
            priority: sum(1 for row in rows if row["prioridade"] == priority)
            for priority in ("alta", "media", "baixa", "ok")
        }
        summary = {
            "pares_analisados": len(rows),
            "arquivos_ausentes": missing,
            "falhas_de_leitura": failures,
            "contagem_por_prioridade": counts,
            "suspeitos_total": len(suspicious),
            "itens_no_relatorio_priorizado": len(selected),
            "seleção_jsonl": str(args.selection_jsonl.resolve()) if args.selection_jsonl else None,
            "relatório_base": str(args.baseline_report.resolve()) if args.baseline_report else None,
            "relatorio_completo": str(args.report.resolve()),
            "relatorio_priorizado": str(args.review_report.resolve()),
            "nota": (
                "Triagem acústica heurística. Pausas estilísticas e fragmentos que se "
                "parecem com fala legítima ainda podem exigir audição ou ASR."
            ),
        }
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        with args.summary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        known = next((row for row in rows if row["id_hex"] == "0x0004fbb0"), None)
        print(f"Prioridades: alta={counts['alta']}, média={counts['media']}, baixa={counts['baixa']}, ok={counts['ok']}")
        if known:
            print(
                "Controle 0x0004fbb0: "
                f"prioridade={known['prioridade']}, risco={known['risk_score']}, "
                f"motivos={known['motivos']}"
            )
        print(f"Relatório completo: {args.report}")
        print(f"Revisão priorizada: {args.review_report}")
        print(f"Resumo: {args.summary}")
        if missing or failures:
            print(
                f"AVISO: ausentes={len(missing)}, falhas_de_leitura={len(failures)}",
                file=sys.stderr,
            )
            return 1
        return 0
    except AuditError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
