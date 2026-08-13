#!/usr/bin/env python3
"""Seleciona a melhor de varias regeneracoes para cada ID confirmado.

O criterio principal e evitar a troca acidental para uma voz masculina. A
duracao e usada apenas como desempate; o pos-processamento adaptativo cuidara
do ajuste final de tempo.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


def as_float(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def analyze_pitch(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "exists": False,
            "duration_s": math.nan,
            "frames": 0,
            "median_hz": math.nan,
            "p10_hz": math.nan,
            "p90_hz": math.nan,
            "fraction_below_160": math.nan,
            "median_probability": math.nan,
        }

    info = sf.info(path)
    duration = info.frames / info.samplerate if info.samplerate else math.nan
    signal, sr = librosa.load(path, sr=16_000, mono=True)
    signal = np.nan_to_num(signal.astype(np.float32, copy=False))
    trimmed, _ = librosa.effects.trim(
        signal,
        top_db=38,
        frame_length=1024,
        hop_length=160,
    )
    if trimmed.size >= 512:
        signal = trimmed

    f0, _, probability = librosa.pyin(
        signal,
        fmin=65.0,
        fmax=400.0,
        sr=sr,
        frame_length=1024,
        hop_length=160,
    )
    probability = np.asarray(probability, dtype=np.float64)
    keep = np.isfinite(f0) & np.isfinite(probability) & (probability >= 0.35)
    voiced = f0[keep]
    if voiced.size == 0:
        return {
            "exists": True,
            "duration_s": duration,
            "frames": 0,
            "median_hz": math.nan,
            "p10_hz": math.nan,
            "p90_hz": math.nan,
            "fraction_below_160": math.nan,
            "median_probability": (
                float(np.nanmedian(probability))
                if np.any(np.isfinite(probability))
                else math.nan
            ),
        }

    return {
        "exists": True,
        "duration_s": duration,
        "frames": int(voiced.size),
        "median_hz": float(np.median(voiced)),
        "p10_hz": float(np.percentile(voiced, 10)),
        "p90_hz": float(np.percentile(voiced, 90)),
        "fraction_below_160": float(np.mean(voiced < 160.0)),
        "median_probability": float(np.median(probability[keep])),
    }


def display(value: object, digits: int = 4) -> object:
    if isinstance(value, float):
        return round(value, digits) if math.isfinite(value) else ""
    return value


def score(metrics: dict[str, object], target_hz: float, original_duration: float) -> float:
    median = as_float(metrics["median_hz"])
    frames = int(metrics["frames"])
    fraction = as_float(metrics["fraction_below_160"])
    probability = as_float(metrics["median_probability"])
    duration = as_float(metrics["duration_s"])
    if not math.isfinite(median):
        return 10_000.0

    result = 0.0
    if math.isfinite(target_hz) and target_hz > 0:
        cents = abs(1200.0 * math.log2(median / target_hz))
        result += cents / 50.0
    else:
        result += abs(median - 195.0) / 5.0

    # A troca de identidade vocal e muito mais grave que uma pequena diferenca
    # de prosodia ou de duracao.
    if median < 150.0:
        result += 160.0 + (150.0 - median) * 3.0
    elif median < 165.0:
        result += 80.0 + (165.0 - median) * 2.0
    if math.isfinite(fraction):
        result += fraction * 28.0
    if frames < 4:
        result += 35.0
    if math.isfinite(probability) and probability < 0.45:
        result += (0.45 - probability) * 30.0
    if (
        math.isfinite(duration)
        and math.isfinite(original_duration)
        and duration > 0
        and original_duration > 0
    ):
        result += abs(math.log(duration / original_duration)) * 2.0
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--attempt-dir", type=Path, action="append", required=True)
    parser.add_argument("--pandora-dir", type=Path, required=True)
    parser.add_argument("--old-reference-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--selected-dir", type=Path, required=True)
    parser.add_argument("--comparison-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    with args.jsonl.open("r", encoding="utf-8-sig") as handle:
        items = [json.loads(line) for line in handle if line.strip()]
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        manifest = {
            row["id_hex"].lower(): row
            for row in csv.DictReader(handle, delimiter=";")
        }

    args.selected_dir.mkdir(parents=True, exist_ok=True)
    args.comparison_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    selected = 0
    auto_ok = 0

    for item_index, item in enumerate(items, 1):
        ident = str(item["id"]).lower()
        manifest_row = manifest.get(ident, {})
        original_duration = as_float(manifest_row.get("duracao_original"))
        previous: list[tuple[str, Path, dict[str, object]]] = []
        for label, folder in (
            ("pandora", args.pandora_dir),
            ("referencia_antiga", args.old_reference_dir),
        ):
            previous_path = folder / f"{ident}.wav"
            previous.append((label, previous_path, analyze_pitch(previous_path)))
        previous_medians = [
            as_float(metrics["median_hz"])
            for _, _, metrics in previous
            if int(metrics["frames"]) >= 3
        ]
        previous_medians = [value for value in previous_medians if math.isfinite(value)]
        # O maximo e intencional: em dois IDs curtos a versao Pandora tambem
        # havia saído masculina, enquanto a referencia antiga era feminina.
        target_hz = max(previous_medians) if previous_medians else math.nan

        attempts: list[tuple[int, Path, dict[str, object], float]] = []
        for attempt_index, folder in enumerate(args.attempt_dir, 1):
            wav = folder / f"{ident}.wav"
            metrics = analyze_pitch(wav)
            attempt_score = score(metrics, target_hz, original_duration)
            attempts.append((attempt_index, wav, metrics, attempt_score))

        best = min(attempts, key=lambda value: value[3])
        best_index, best_path, best_metrics, best_score = best
        if not best_path.is_file():
            raise FileNotFoundError(best_path)
        destination = args.selected_dir / f"{ident}.wav"
        shutil.copy2(best_path, destination)
        selected += 1

        per_id = args.comparison_dir / ident
        per_id.mkdir(parents=True, exist_ok=True)
        for attempt_index, wav, _, _ in attempts:
            shutil.copy2(wav, per_id / f"tentativa_{attempt_index}.wav")

        best_median = as_float(best_metrics["median_hz"])
        best_fraction = as_float(best_metrics["fraction_below_160"])
        best_frames = int(best_metrics["frames"])
        status = (
            "aprovada_pitch"
            if best_frames >= 4
            and math.isfinite(best_median)
            and best_median >= 165.0
            and (not math.isfinite(best_fraction) or best_fraction < 0.60)
            else "revisar_identidade"
        )
        if status == "aprovada_pitch":
            auto_ok += 1

        for attempt_index, wav, metrics, attempt_score in attempts:
            row: dict[str, object] = {
                "id_hex": ident,
                "texto": item.get("text", ""),
                "tentativa": attempt_index,
                "selecionada": "sim" if attempt_index == best_index else "nao",
                "status_selecionada": status if attempt_index == best_index else "",
                "score": round(attempt_score, 4),
                "f0_alvo_anterior_hz": display(target_hz),
                "duracao_original_s": display(original_duration, 6),
                "wav": str(wav.resolve()),
            }
            row.update({key: display(value, 6) for key, value in metrics.items()})
            rows.append(row)

        print(
            f"{item_index}/{len(items)} {ident}: tentativa {best_index}; "
            f"f0={display(best_median, 1)} Hz; {status}",
            flush=True,
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Selecionadas: {selected}/{len(items)}", flush=True)
    print(f"Aprovadas por pitch: {auto_ok}/{len(items)}", flush=True)
    print(f"Relatorio: {args.report.resolve()}", flush=True)
    print(f"WAVs selecionados: {args.selected_dir.resolve()}", flush=True)
    return 0 if selected == len(items) else 2


if __name__ == "__main__":
    raise SystemExit(main())
