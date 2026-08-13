#!/usr/bin/env python3
"""Seleciona candidatos expressivos usando apenas métricas prosódicas normalizadas."""

from __future__ import annotations

import argparse
import csv
import math
import re
import statistics
import sys
from dataclasses import asdict
from pathlib import Path

from analisar_prosodia_comparativa import ProsodyError, analyze_wav, normalize_id


class SelectionError(RuntimeError):
    pass


def read_texts(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames or "id_hex" not in reader.fieldnames:
            raise SelectionError(f"manifesto sem id_hex: {path}")
        for row in reader:
            try:
                ident = normalize_id(row.get("id_hex") or "")
            except ProsodyError:
                continue
            text = (
                row.get("texto_final")
                or row.get("texto_original")
                or row.get("texto")
                or ""
            ).strip()
            result[ident] = text
    if not result:
        raise SelectionError(f"nenhum texto encontrado no manifesto: {path}")
    return result


def text_preselection_score(text: str, duration: float) -> float:
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    score = min(len(words), 35) / 10.0
    score += 1.5 * (text.count("?") + text.count("!"))
    score += 0.7 * (text.count("...") + text.count("…"))
    score += 0.25 * sum(text.count(token) for token in (",", ";", ":"))
    score += 0.2 * min(text.count("."), 4)
    score -= abs(duration - 6.5) * 0.08
    return score


def robust_z(values: list[float]) -> list[float]:
    if not values:
        return []
    center = statistics.median(values)
    deviations = [abs(value - center) for value in values]
    mad = statistics.median(deviations)
    if mad < 1e-9:
        spread = statistics.pstdev(values)
        if spread < 1e-9:
            return [0.0] * len(values)
        return [(value - center) / spread for value in values]
    return [0.6745 * (value - center) / mad for value in values]


def add_expression_scores(rows: list[dict[str, object]]) -> None:
    feature_weights = {
        "pitch_span_st": 0.35,
        "pitch_std_st": 0.20,
        "pitch_motion_st": 0.10,
        "energy_span_db": 0.25,
        "pause_ratio": 0.10,
    }
    scores = [0.0] * len(rows)
    for feature, weight in feature_weights.items():
        values = [float(row[feature]) for row in rows]
        for index, value in enumerate(robust_z(values)):
            scores[index] += weight * max(-3.0, min(3.0, value))
    for row, score in zip(rows, scores, strict=True):
        pause_ratio = float(row["pause_ratio"])
        if pause_ratio > 0.35:
            score -= (pause_ratio - 0.35) * 5.0
        row["expressiveness_score"] = round(score, 4)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-duration", type=float, default=4.5)
    parser.add_argument("--max-duration", type=float, default=10.0)
    parser.add_argument("--preselect", type=int, default=120)
    parser.add_argument("--top", type=int, default=12)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        import soundfile as sf

        if not args.input.is_dir():
            raise SelectionError(f"pasta não encontrada: {args.input}")
        if not args.manifest.is_file():
            raise SelectionError(f"manifesto não encontrado: {args.manifest}")
        if not 0 < args.min_duration < args.max_duration:
            raise SelectionError("faixa de duração inválida")
        if args.preselect < args.top or args.top < 1:
            raise SelectionError("--preselect deve ser maior ou igual a --top")

        texts = read_texts(args.manifest)
        candidates: list[tuple[float, str, Path, float, str]] = []
        for path in args.input.glob("*.wav"):
            try:
                ident = normalize_id(path.stem)
            except ProsodyError:
                continue
            text = texts.get(ident, "")
            if not text:
                continue
            try:
                duration = float(sf.info(path).duration)
            except Exception:
                continue
            if args.min_duration <= duration <= args.max_duration:
                score = text_preselection_score(text, duration)
                candidates.append((score, ident, path, duration, text))
        if not candidates:
            raise SelectionError("nenhum candidato na faixa de duração")
        candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
        selected = candidates[: args.preselect]
        print(
            f"Candidatos na faixa: {len(candidates)}; "
            f"analisando pré-seleção: {len(selected)}"
        )

        rows: list[dict[str, object]] = []
        for number, (_, ident, path, duration, text) in enumerate(selected, start=1):
            print(f"[{number}/{len(selected)}] {ident}")
            try:
                metrics = analyze_wav(path)
            except ProsodyError as exc:
                print(f"  ignorado: {exc}", file=sys.stderr)
                continue
            row: dict[str, object] = {
                "id": ident,
                "path": str(path.resolve()),
                "texto": text,
                "duration_source_s": round(duration, 4),
            }
            row.update(asdict(metrics))
            rows.append(row)
        if not rows:
            raise SelectionError("nenhum candidato pôde ser analisado")

        add_expression_scores(rows)
        rows.sort(
            reverse=True,
            key=lambda row: (float(row["expressiveness_score"]), str(row["id"])),
        )
        rows = rows[: args.top]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        print(f"Selecionados: {len(rows)}")
        for index, row in enumerate(rows, start=1):
            print(
                f"{index}. {row['id']} | {row['duration_source_s']:.2f}s | "
                f"score={row['expressiveness_score']:.2f} | {row['texto']}"
            )
        print(f"Relatório: {args.output}")
        return 0
    except (SelectionError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
