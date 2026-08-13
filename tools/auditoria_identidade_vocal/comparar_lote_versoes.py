#!/usr/bin/env python3
"""Compara o pitch do lote final com duas geracoes femininas anteriores."""

from __future__ import annotations

import argparse
import csv
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


TARGET_SR = 16_000
FRAME_LENGTH = 1024
HOP_LENGTH = 160
WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def pitch(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"mediana_hz": math.nan, "fracao_abaixo_160": math.nan, "quadros": 0}
    signal, sr = sf.read(path, dtype="float32", always_2d=False)
    if signal.ndim == 2:
        signal = signal.mean(axis=1, dtype=np.float32)
    signal = np.nan_to_num(signal.astype(np.float32, copy=False))
    if sr != TARGET_SR:
        divisor = math.gcd(int(sr), TARGET_SR)
        signal = resample_poly(
            signal,
            TARGET_SR // divisor,
            int(sr) // divisor,
        ).astype(np.float32, copy=False)
    signal -= float(np.mean(signal))
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak <= 1e-6:
        return {"mediana_hz": math.nan, "fracao_abaixo_160": math.nan, "quadros": 0}
    signal /= peak
    trimmed, _ = librosa.effects.trim(
        signal,
        top_db=38,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
    )
    if trimmed.size >= FRAME_LENGTH:
        signal = trimmed
    f0 = librosa.yin(
        signal,
        fmin=65.0,
        fmax=400.0,
        sr=TARGET_SR,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        trough_threshold=0.15,
    )
    rms = librosa.feature.rms(
        y=signal,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        center=True,
    )[0]
    size = min(f0.size, rms.size)
    floor = max(float(np.quantile(rms[:size], 0.20)), 10 ** (-42.0 / 20.0))
    voiced = f0[:size][(rms[:size] >= floor) & np.isfinite(f0[:size])]
    if not voiced.size:
        return {"mediana_hz": math.nan, "fracao_abaixo_160": math.nan, "quadros": 0}
    return {
        "mediana_hz": round(float(np.median(voiced)), 4),
        "fracao_abaixo_160": round(float(np.mean(voiced < 160.0)), 6),
        "quadros": int(voiced.size),
    }


def finite(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def analyze(row: dict[str, str], pandora_dir: Path, old_dir: Path) -> dict[str, object]:
    ident = row["id_hex"]
    pandora = pitch(pandora_dir / f"{ident}.wav")
    old = pitch(old_dir / f"{ident}.wav")
    current = finite(row.get("f0_mediana_hz"))
    previous_values = [
        value
        for value in (finite(pandora["mediana_hz"]), finite(old["mediana_hz"]))
        if math.isfinite(value)
    ]
    best_previous = max(previous_values) if previous_values else math.nan
    median_previous = float(np.median(previous_values)) if previous_values else math.nan
    best_gap = best_previous - current if math.isfinite(best_previous) else math.nan
    median_gap = median_previous - current if math.isfinite(median_previous) else math.nan
    words = len(WORD_RE.findall(row.get("texto", "")))
    duration = finite(row.get("duracao_s"))

    priority = "ok"
    reason = ""
    complete = words >= 2 and duration >= 0.8
    if complete and current <= 160.0 and best_gap >= 35.0:
        priority = "alta"
        reason = "fala completa com pitch muito baixo e grande queda ante geracoes femininas"
    elif complete and current <= 175.0 and best_gap >= 30.0:
        priority = "media"
        reason = "fala completa com pitch baixo e queda consistente ante geracoes femininas"
    elif not complete and current <= 165.0 and best_gap >= 35.0:
        priority = "curta"
        reason = "vocalizacao/fala curta com forte queda de pitch; escuta obrigatoria"

    result: dict[str, object] = dict(row)
    result.update(
        {
            "pandora_f0_mediana_hz": pandora["mediana_hz"],
            "pandora_fracao_abaixo_160": pandora["fracao_abaixo_160"],
            "pandora_quadros_pitch": pandora["quadros"],
            "referencia_antiga_f0_mediana_hz": old["mediana_hz"],
            "referencia_antiga_fracao_abaixo_160": old["fracao_abaixo_160"],
            "referencia_antiga_quadros_pitch": old["quadros"],
            "melhor_f0_anterior_hz": round(best_previous, 4) if math.isfinite(best_previous) else "",
            "mediana_f0_anterior_hz": round(median_previous, 4) if math.isfinite(median_previous) else "",
            "queda_para_melhor_anterior_hz": round(best_gap, 4) if math.isfinite(best_gap) else "",
            "queda_para_mediana_anterior_hz": round(median_gap, 4) if math.isfinite(median_gap) else "",
            "prioridade_diferencial": priority,
            "motivo_diferencial": reason,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-csv", type=Path, required=True)
    parser.add_argument("--pandora-dir", type=Path, required=True)
    parser.add_argument("--old-reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidates-output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    with args.audit_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    print(f"Comparando {len(rows)} IDs com duas geracoes anteriores...", flush=True)

    started = time.monotonic()
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(analyze, row, args.pandora_dir, args.old_reference_dir): row
            for row in rows
        }
        for count, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if count == 1 or count % 500 == 0 or count == len(rows):
                elapsed = time.monotonic() - started
                rate = count / max(elapsed, 1e-9)
                remaining = (len(rows) - count) / max(rate, 1e-9)
                print(
                    f"Progresso: {count}/{len(rows)} "
                    f"({rate:.1f} ID/s; restante ~{remaining/60:.1f} min)",
                    flush=True,
                )

    order = {"alta": 0, "media": 1, "curta": 2, "ok": 3}
    results.sort(
        key=lambda row: (
            order[str(row["prioridade_diferencial"])],
            -finite(row["queda_para_melhor_anterior_hz"]),
            row["id_hex"],
        )
    )
    candidates = [row for row in results if row["prioridade_diferencial"] != "ok"]

    fields = list(results[0]) if results else []
    for path, data in ((args.output, results), (args.candidates_output, candidates)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(data)
    counts = {
        key: sum(row["prioridade_diferencial"] == key for row in results)
        for key in ("alta", "media", "curta", "ok")
    }
    print(f"Resultado diferencial: {counts}", flush=True)
    print(f"Candidatos: {args.candidates_output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
