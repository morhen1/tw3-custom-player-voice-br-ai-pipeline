#!/usr/bin/env python3
"""Compara prosódia normalizada entre pares de WAVs com o mesmo ID.

O relatório contém somente medidas acústicas agregadas. O script não copia áudio,
não cria embeddings de locutor e não envia arquivos para um modelo de voz.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


class ProsodyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProsodyMetrics:
    duration_s: float
    voiced_ratio: float
    pitch_median_hz: float
    pitch_span_st: float
    pitch_std_st: float
    pitch_motion_st: float
    energy_span_db: float
    pause_ratio: float
    pause_count: int


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if len(token) != 10 or not token.startswith("0x"):
        raise ProsodyError(f"ID inválido: {value}")
    try:
        int(token[2:], 16)
    except ValueError as exc:
        raise ProsodyError(f"ID inválido: {value}") from exc
    return token


def read_selection(path: Path) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProsodyError(
                    f"{path}, linha {line_number}: JSON inválido"
                ) from exc
            ident = normalize_id(str(payload.get("id", "")))
            if ident in seen:
                raise ProsodyError(f"ID repetido na seleção: {ident}")
            seen.add(ident)
            selected.append((ident, str(payload.get("text", "")).strip()))
    if not selected:
        raise ProsodyError(f"seleção vazia: {path}")
    return selected


def index_wavs(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        raise ProsodyError(f"pasta não encontrada: {folder}")
    indexed: dict[str, Path] = {}
    for path in folder.glob("*.wav"):
        try:
            ident = normalize_id(path.stem)
        except ProsodyError:
            continue
        if ident in indexed:
            raise ProsodyError(f"WAV duplicado para {ident} em {folder}")
        indexed[ident] = path
    if not indexed:
        raise ProsodyError(f"nenhum WAV nomeado por ID em {folder}")
    return indexed


def count_runs(mask: Iterable[bool], minimum_frames: int) -> int:
    count = 0
    run = 0
    for state in mask:
        if state:
            run += 1
        else:
            if run >= minimum_frames:
                count += 1
            run = 0
    if run >= minimum_frames:
        count += 1
    return count


def _percentile(values, percentile: float) -> float:
    import numpy as np

    return float(np.percentile(values, percentile))


def analyze_wav(path: Path, sample_rate: int = 16000) -> ProsodyMetrics:
    try:
        import librosa
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise ProsodyError(
            "a análise requer numpy, librosa e soundfile no mesmo Python"
        ) from exc

    try:
        audio, source_rate = sf.read(path, dtype="float32", always_2d=False)
    except Exception as exc:  # soundfile fornece exceções diferentes por formato
        raise ProsodyError(f"não foi possível abrir {path}: {exc}") from exc
    if audio.ndim == 2:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    audio = audio[np.isfinite(audio)]
    if audio.size == 0 or float(np.max(np.abs(audio))) < 1e-6:
        raise ProsodyError(f"áudio vazio ou silencioso: {path}")
    if source_rate != sample_rate:
        audio = librosa.resample(audio, orig_sr=source_rate, target_sr=sample_rate)

    trimmed, _ = librosa.effects.trim(audio, top_db=45, frame_length=1024, hop_length=160)
    if trimmed.size < int(sample_rate * 0.08):
        raise ProsodyError(f"fala curta demais após aparar silêncio: {path}")
    duration_s = float(trimmed.size / sample_rate)

    frame_length = 1024
    hop_length = 160
    if trimmed.size < frame_length:
        trimmed = np.pad(trimmed, (0, frame_length - trimmed.size))

    rms = librosa.feature.rms(
        y=trimmed, frame_length=frame_length, hop_length=hop_length, center=True
    )[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max)
    active = rms_db > -35.0
    active_values = rms_db[active]
    energy_span_db = (
        _percentile(active_values, 90) - _percentile(active_values, 10)
        if active_values.size >= 3
        else 0.0
    )
    pause_mask = rms_db <= -35.0
    pause_count = count_runs(pause_mask.tolist(), minimum_frames=12)
    pause_ratio = float(np.mean(pause_mask)) if pause_mask.size else 0.0

    try:
        f0, voiced_flag, _ = librosa.pyin(
            trimmed,
            fmin=65.0,
            fmax=500.0,
            sr=sample_rate,
            frame_length=frame_length,
            hop_length=hop_length,
            center=True,
        )
    except Exception as exc:
        raise ProsodyError(f"falha ao estimar pitch de {path}: {exc}") from exc
    valid = np.isfinite(f0) & np.asarray(voiced_flag, dtype=bool)
    voiced_f0 = np.asarray(f0[valid], dtype=np.float64)
    if voiced_f0.size < 3:
        raise ProsodyError(f"pitch insuficiente para analisar: {path}")

    pitch_median_hz = float(np.median(voiced_f0))
    pitch_st = 12.0 * np.log2(voiced_f0 / pitch_median_hz)
    pitch_span_st = _percentile(pitch_st, 90) - _percentile(pitch_st, 10)
    pitch_std_st = float(np.std(pitch_st))
    pitch_motion_st = (
        float(np.median(np.abs(np.diff(pitch_st)))) if pitch_st.size > 1 else 0.0
    )
    voiced_ratio = float(np.mean(valid)) if valid.size else 0.0

    return ProsodyMetrics(
        duration_s=duration_s,
        voiced_ratio=voiced_ratio,
        pitch_median_hz=pitch_median_hz,
        pitch_span_st=pitch_span_st,
        pitch_std_st=pitch_std_st,
        pitch_motion_st=pitch_motion_st,
        energy_span_db=energy_span_db,
        pause_ratio=pause_ratio,
        pause_count=pause_count,
    )


def finite_median(values: Iterable[float]) -> float:
    filtered = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.median(filtered) if filtered else 0.0


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        raise ProsodyError("nenhum par válido para resumir")

    def median_delta(name: str) -> float:
        return finite_median(
            float(row[f"antigo_{name}"]) - float(row[f"atual_{name}"])
            for row in rows
        )

    duration_ratio = finite_median(
        float(row["antigo_duration_s"]) / float(row["atual_duration_s"])
        for row in rows
        if float(row["atual_duration_s"]) > 0
    )
    pitch_delta = median_delta("pitch_span_st")
    motion_delta = median_delta("pitch_motion_st")
    energy_delta = median_delta("energy_span_db")
    pause_delta = median_delta("pause_ratio")

    observations: list[str] = []
    if pitch_delta > 0.75:
        observations.append("O conjunto antigo tem maior amplitude de entonação.")
    elif pitch_delta < -0.75:
        observations.append("O conjunto atual tem maior amplitude de entonação.")
    else:
        observations.append("A amplitude de entonação é semelhante nos dois conjuntos.")
    if energy_delta > 1.5:
        observations.append("O conjunto antigo tem maior contraste de intensidade.")
    elif energy_delta < -1.5:
        observations.append("O conjunto atual tem maior contraste de intensidade.")
    if duration_ratio < 0.90:
        observations.append("O conjunto antigo entrega as falas mais rapidamente.")
    elif duration_ratio > 1.10:
        observations.append("O conjunto antigo entrega as falas mais lentamente.")
    if pause_delta > 0.04:
        observations.append("O conjunto antigo usa proporcionalmente mais pausas.")
    elif pause_delta < -0.04:
        observations.append("O conjunto atual usa proporcionalmente mais pausas.")

    return {
        "pares_validos": len(rows),
        "medianas_antigo_menos_atual": {
            "pitch_span_st": round(pitch_delta, 4),
            "pitch_motion_st": round(motion_delta, 4),
            "energy_span_db": round(energy_delta, 4),
            "pause_ratio": round(pause_delta, 4),
        },
        "mediana_razao_duracao_antigo_atual": round(duration_ratio, 4),
        "observacoes": observations,
        "aviso": (
            "Métricas normalizadas e descritivas; não representam autorização "
            "jurídica nem removem direitos associados aos áudios de origem."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--antigo", type=Path, required=True, help="pasta dos WAVs antigos")
    parser.add_argument("--atual", type=Path, required=True, help="pasta dos WAVs autorizados")
    parser.add_argument("--selection-jsonl", type=Path, required=True)
    parser.add_argument("--report-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument(
        "--skip-analysis-errors",
        action="store_true",
        help="ignora pares curtos ou sem pitch suficiente e continua a análise",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.selection_jsonl.is_file():
            raise ProsodyError(f"seleção não encontrada: {args.selection_jsonl}")
        selected = read_selection(args.selection_jsonl)
        old_wavs = index_wavs(args.antigo)
        current_wavs = index_wavs(args.atual)

        missing_old = [ident for ident, _ in selected if ident not in old_wavs]
        missing_current = [ident for ident, _ in selected if ident not in current_wavs]
        if missing_old or missing_current:
            details = []
            if missing_old:
                details.append(f"ausentes no antigo: {', '.join(missing_old)}")
            if missing_current:
                details.append(f"ausentes no atual: {', '.join(missing_current)}")
            raise ProsodyError("; ".join(details))

        rows: list[dict[str, object]] = []
        skipped: list[dict[str, str]] = []
        for number, (ident, text) in enumerate(selected, start=1):
            print(f"[{number}/{len(selected)}] Analisando {ident}")
            try:
                old_metrics = analyze_wav(old_wavs[ident])
                current_metrics = analyze_wav(current_wavs[ident])
            except ProsodyError as exc:
                if not args.skip_analysis_errors:
                    raise
                print(f"  Ignorado: {exc}")
                skipped.append({"id": ident, "motivo": str(exc)})
                continue
            row: dict[str, object] = {"id": ident, "texto": text}
            row.update({f"antigo_{key}": value for key, value in asdict(old_metrics).items()})
            row.update({f"atual_{key}": value for key, value in asdict(current_metrics).items()})
            rows.append(row)

        summary = summarize(rows)
        summary["pares_ignorados"] = skipped
        args.report_csv.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with args.summary_json.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        print(f"Pares válidos: {len(rows)}")
        print(f"Pares ignorados: {len(skipped)}")
        print(f"Relatório: {args.report_csv}")
        print(f"Resumo: {args.summary_json}")
        for observation in summary["observacoes"]:
            print(f"- {observation}")
        return 0
    except ProsodyError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
