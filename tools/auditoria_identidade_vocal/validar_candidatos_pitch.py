#!/usr/bin/env python3
"""Revalida candidatos de identidade vocal com pYIN e versoes anteriores."""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import librosa
import numpy as np


WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def pyin_metrics(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "existe": False,
            "quadros": 0,
            "mediana_hz": "",
            "p10_hz": "",
            "p90_hz": "",
            "fracao_abaixo_160": "",
            "probabilidade_mediana": "",
        }
    signal, sr = librosa.load(path, sr=16_000, mono=True)
    signal, _ = librosa.effects.trim(signal, top_db=38)
    f0, _, probability = librosa.pyin(
        signal,
        fmin=65.0,
        fmax=400.0,
        sr=sr,
        frame_length=1024,
        hop_length=160,
    )
    keep = np.isfinite(f0) & (probability >= 0.35)
    voiced = f0[keep]
    if not voiced.size:
        return {
            "existe": True,
            "quadros": 0,
            "mediana_hz": "",
            "p10_hz": "",
            "p90_hz": "",
            "fracao_abaixo_160": "",
            "probabilidade_mediana": round(float(np.nanmedian(probability)), 6),
        }
    return {
        "existe": True,
        "quadros": int(voiced.size),
        "mediana_hz": round(float(np.median(voiced)), 4),
        "p10_hz": round(float(np.percentile(voiced, 10)), 4),
        "p90_hz": round(float(np.percentile(voiced, 90)), 4),
        "fracao_abaixo_160": round(float(np.mean(voiced < 160.0)), 6),
        "probabilidade_mediana": round(float(np.nanmedian(probability)), 6),
    }


def prefix(row: dict[str, object], name: str, metrics: dict[str, object]) -> None:
    for key, value in metrics.items():
        row[f"{name}_{key}"] = value


def as_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-csv", type=Path, required=True)
    parser.add_argument("--pandora-dir", type=Path, required=True)
    parser.add_argument("--old-reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--priorities", default="alta,media")
    parser.add_argument("--priority-column", default="prioridade_identidade")
    args = parser.parse_args()

    priorities = {value.strip() for value in args.priorities.split(",") if value.strip()}
    with args.audit_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = [
            row
            for row in csv.DictReader(handle, delimiter=";")
            if row.get(args.priority_column) in priorities
        ]

    results: list[dict[str, object]] = []
    for index, source in enumerate(source_rows, 1):
        ident = source["id_hex"]
        row: dict[str, object] = {
            "id_hex": ident,
            "prioridade_triagem": source[args.priority_column],
            "texto": source.get("texto", ""),
            "estilo": source.get("estilo", ""),
            "fonte": source.get("fonte", ""),
            "duracao_s": source.get("duracao_s", ""),
            "wav_final": source.get("wav", ""),
        }
        current = pyin_metrics(Path(source["wav"]))
        pandora_path = args.pandora_dir / f"{ident}.wav"
        old_path = args.old_reference_dir / f"{ident}.wav"
        pandora = pyin_metrics(pandora_path)
        old = pyin_metrics(old_path)
        prefix(row, "final", current)
        prefix(row, "pandora", pandora)
        prefix(row, "referencia_antiga", old)

        words = len(WORD_RE.findall(str(source.get("texto", ""))))
        duration = as_float(source.get("duracao_s"))
        median = as_float(current["mediana_hz"])
        fraction = as_float(current["fracao_abaixo_160"])
        frames = int(current["quadros"])
        comparison_medians = [
            as_float(pandora["mediana_hz"]),
            as_float(old["mediana_hz"]),
        ]
        valid_comparisons = [value for value in comparison_medians if math.isfinite(value)]
        comparison_gap = (
            float(np.median(valid_comparisons)) - median
            if valid_comparisons and math.isfinite(median)
            else math.nan
        )

        if words <= 1 or duration < 0.8:
            decision = "vocalizacao_curta_inconclusiva"
            reason = "fala curta/vocalizacao; pitch isolado nao comprova troca de voz"
        elif frames >= 8 and median <= 155.0 and fraction >= 0.65:
            decision = "forte_suspeita_masculina"
            reason = "pYIN confirma pitch predominantemente masculino"
            if math.isfinite(comparison_gap) and comparison_gap >= 30.0:
                reason += f"; versoes anteriores ficaram ~{comparison_gap:.0f} Hz acima"
        elif frames >= 8 and median <= 172.0 and fraction >= 0.55:
            decision = "suspeita_moderada"
            reason = "pYIN confirma pitch baixo em parte dominante da fala"
        elif frames < 8:
            decision = "pitch_insuficiente"
            reason = "poucos quadros periodicos para decisao automatica"
        else:
            decision = "provavel_falso_positivo"
            reason = "pYIN nao confirmou predominancia masculina"
        row["decisao_validacao"] = decision
        row["motivo_validacao"] = reason
        row["diferenca_mediana_versoes_anteriores_hz"] = (
            round(comparison_gap, 4) if math.isfinite(comparison_gap) else ""
        )
        row["pandora_wav"] = str(pandora_path)
        row["referencia_antiga_wav"] = str(old_path)
        results.append(row)
        print(f"Validado {index}/{len(source_rows)}: {ident} -> {decision}", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(results[0]) if results else []
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(results)
    print(f"Relatorio: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
