#!/usr/bin/env python3
"""Cria um CSV acústico enriquecido a partir de falas oficiais decodificadas."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("ERRO: a análise requer numpy no mesmo Python") from exc

from auditar_qualidade_wavs import (
    AuditError,
    _bridge_tiny_silences,
    _decode_pcm,
    _runs,
    analyze_wav,
    normalize_id,
    text_metrics,
)


ELLIPSIS_RE = re.compile(r"\.\.\.|…")


class AnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectedLine:
    ident: str
    text: str


@dataclass(frozen=True)
class PauseInterval:
    start_ms: float
    duration_ms: float


def read_selection(path: Path) -> list[SelectedLine]:
    rows: list[SelectedLine] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise AnalysisError(f"{path}, linha {line_number}: JSON inválido") from exc
        try:
            ident = normalize_id(str(record.get("id", "")))
        except AuditError as exc:
            raise AnalysisError(f"{path}, linha {line_number}: {exc}") from exc
        text = str(record.get("text", "")).strip()
        if not text:
            raise AnalysisError(f"{path}, linha {line_number}: texto vazio")
        if ident in seen:
            raise AnalysisError(f"{path}, linha {line_number}: ID repetido {ident}")
        seen.add(ident)
        rows.append(SelectedLine(ident, text))
    if not rows:
        raise AnalysisError(f"seleção vazia: {path}")
    return rows


def read_csv_by_id(path: Path, id_column: str = "id_hex") -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        raw_ident = row.get(id_column, "")
        if not raw_ident:
            continue
        try:
            ident = normalize_id(raw_ident)
        except AuditError:
            continue
        result[ident] = row
    return result


def pause_intervals(path: Path, frame_ms: float = 10.0) -> list[PauseInterval]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_width = handle.getsampwidth()
            frame_count = handle.getnframes()
            compression = handle.getcomptype()
            payload = handle.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise AnalysisError(f"não foi possível abrir {path}: {exc}") from exc
    if compression != "NONE" or channels < 1 or frame_count < 1:
        raise AnalysisError(f"WAV PCM inválido: {path}")
    samples = _decode_pcm(payload, sample_width)
    if samples.size % channels:
        raise AnalysisError(f"WAV com amostras incompletas: {path}")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)
    samples = np.nan_to_num(samples.astype(np.float32, copy=False))
    frame_samples = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    energy_frames = int(math.ceil(samples.size / frame_samples))
    padding = energy_frames * frame_samples - samples.size
    framed = np.pad(samples, (0, padding)).reshape(energy_frames, frame_samples)
    energy = np.sqrt(np.mean(framed.astype(np.float64) ** 2, axis=1))
    energy_db = 20.0 * np.log10(np.maximum(energy, 1e-12))
    p90 = float(np.percentile(energy_db, 90))
    threshold = max(-50.0, min(-36.0, p90 - 32.0))
    active = _bridge_tiny_silences(energy_db > threshold, maximum_frames=2)
    indexes = np.flatnonzero(active)
    if indexes.size == 0:
        return []
    first = int(indexes[0])
    last = int(indexes[-1])
    internal = active[first : last + 1]
    intervals: list[PauseInterval] = []
    for start, end in _runs(internal, False):
        if start == 0 or end == internal.size:
            continue
        duration_ms = (end - start) * frame_ms
        if duration_ms >= 35.0:
            intervals.append(
                PauseInterval(
                    start_ms=(first + start) * frame_ms,
                    duration_ms=duration_ms,
                )
            )
    return intervals


def duration_class(active_duration_s: float) -> str:
    if active_duration_s < 1.2:
        return "curta"
    if active_duration_s < 4.0:
        return "media"
    return "longa"


def pace_class(syllables_per_s: float) -> str:
    if syllables_per_s < 4.5:
        return "lento"
    if syllables_per_s <= 7.0:
        return "normal"
    return "rapido"


def pause_class(count: int, total_ms: float) -> str:
    if count == 0:
        return "sem_pausa"
    if count <= 2 and total_ms <= 500.0:
        return "pausa_leve"
    return "pausa_frequente"


def text_markers(text: str) -> str:
    markers: list[str] = []
    if "?" in text:
        markers.append("pergunta")
    if "!" in text:
        markers.append("exclamacao")
    if ELLIPSIS_RE.search(text):
        markers.append("reticencias")
    return "|".join(markers) if markers else "declarativa"


def write_enriched_csv(
    path: Path,
    selection: Sequence[SelectedLine],
    wav_dir: Path,
    manifest: dict[str, dict[str, str]],
    extraction: dict[str, dict[str, str]],
) -> list[dict[str, object]]:
    measured: list[dict[str, object]] = []
    for item in selection:
        wav_path = wav_dir / f"{item.ident}.wav"
        if not wav_path.is_file():
            raise AnalysisError(f"WAV ausente: {wav_path}")
        metrics = analyze_wav(wav_path)
        intervals = pause_intervals(wav_path)
        text_data = text_metrics(item.text)
        syllables_per_s = text_data["syllables"] / max(metrics.active_duration_s, 0.08)
        measured.append(
            {
                "item": item,
                "wav_path": wav_path,
                "metrics": metrics,
                "intervals": intervals,
                "text_data": text_data,
                "syllables_per_s": syllables_per_s,
            }
        )

    rms_values = np.asarray([entry["metrics"].rms_dbfs for entry in measured], dtype=float)
    low_threshold, high_threshold = np.percentile(rms_values, [33.333, 66.667])
    output_rows: list[dict[str, object]] = []
    for entry in measured:
        item = entry["item"]
        metrics = entry["metrics"]
        intervals = entry["intervals"]
        text_data = entry["text_data"]
        syllables_per_s = float(entry["syllables_per_s"])
        if metrics.rms_dbfs <= low_threshold:
            intensity = "baixa"
        elif metrics.rms_dbfs >= high_threshold:
            intensity = "alta"
        else:
            intensity = "media"
        relevant = [interval for interval in intervals if interval.duration_ms >= 80.0]
        total_pause_ms = sum(interval.duration_ms for interval in intervals)
        duration_label = duration_class(metrics.active_duration_s)
        pace_label = pace_class(syllables_per_s)
        pause_label = pause_class(len(intervals), total_pause_ms)
        profile = (
            f"{duration_label}__ritmo_{pace_label}__int_{intensity}__{pause_label}"
        )
        manifest_row = manifest.get(item.ident, {})
        extraction_row = extraction.get(item.ident, {})
        original_duration = float(manifest_row.get("duracao_original") or 0.0)
        duration_delta_ms = (metrics.duration_s - original_duration) * 1000.0
        review = "sim" if original_duration and abs(duration_delta_ms) > 30.0 else ""
        detail = ""
        if review:
            detail = "duração WAV divergente do manifesto; conferir decodificação"
        output_rows.append(
            {
                "id_hex": item.ident,
                "texto_atual": item.text,
                "pacote_original": extraction_row.get("pacote_original", ""),
                "codec_original": extraction_row.get("codec", ""),
                "duracao_manifesto_s": f"{original_duration:.6f}" if original_duration else "",
                "duracao_audio_s": f"{metrics.duration_s:.6f}",
                "delta_duracao_ms": f"{duration_delta_ms:.1f}" if original_duration else "",
                "duracao_ativa_s": f"{metrics.active_duration_s:.3f}",
                "silencio_inicial_ms": f"{metrics.trim_start_s * 1000.0:.0f}",
                "silencio_final_ms": f"{metrics.tail_margin_ms:.0f}",
                "rms_dbfs": f"{metrics.rms_dbfs:.2f}",
                "pico_dbfs": f"{metrics.peak_dbfs:.2f}",
                "pausas_internas": str(len(intervals)),
                "pausas_relevantes": str(len(relevant)),
                "pausas_posicao_ms": "|".join(
                    f"{interval.start_ms:.0f}+{interval.duration_ms:.0f}"
                    for interval in relevant
                ),
                "maior_pausa_ms": f"{max((p.duration_ms for p in intervals), default=0.0):.0f}",
                "tempo_pausas_ms": f"{total_pause_ms:.0f}",
                "palavras": str(text_data["words"]),
                "silabas_estimadas": str(text_data["syllables"]),
                "silabas_por_s": f"{syllables_per_s:.2f}",
                "classe_duracao": duration_label,
                "classe_ritmo": pace_label,
                "classe_intensidade": intensity,
                "classe_pausas": pause_label,
                "marcadores_texto": text_markers(item.text),
                "perfil_acustico_id": profile,
                "reference_id": "",
                "revisar": review,
                "detalhe": detail,
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(output_rows)
    os.replace(partial, path)
    return output_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gera CSV enriquecido com métricas acústicas de falas oficiais."
    )
    parser.add_argument("--selection-jsonl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--extraction-report", type=Path, required=True)
    parser.add_argument("--wav-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = args.output.resolve()
        if output.exists():
            raise AnalysisError(f"saída já existe: {output}")
        selection = read_selection(args.selection_jsonl.resolve())
        manifest = read_csv_by_id(args.manifest.resolve())
        extraction = read_csv_by_id(args.extraction_report.resolve())
        rows = write_enriched_csv(
            output,
            selection,
            args.wav_dir.resolve(),
            manifest,
            extraction,
        )
        profiles = len({str(row["perfil_acustico_id"]) for row in rows})
        reviews = sum(row["revisar"] == "sim" for row in rows)
        print(f"Falas analisadas: {len(rows)}")
        print(f"Perfis acústicos encontrados: {profiles}")
        print(f"Sinalizadas para revisão: {reviews}")
        print(f"CSV enriquecido: {output}")
        return 0
    except (AnalysisError, AuditError, OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
