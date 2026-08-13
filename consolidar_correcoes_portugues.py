#!/usr/bin/env python3
"""Mescla a camada segura da auditoria sem sobrescrever o correcoes.csv ativo."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


class MergeError(RuntimeError):
    pass


def read_corrections(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "texto", "motivo"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise MergeError(f"cabeçalho incompatível: {path}")
        rows = list(reader)
    seen: set[str] = set()
    for row in rows:
        ident = row["id_hex"].strip().lower()
        if ident in seen:
            raise MergeError(f"ID duplicado em {path}: {ident}")
        seen.add(ident)
        row["id_hex"] = ident
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    base = read_corrections(args.base)
    overlay = read_corrections(args.overlay)
    merged = {row["id_hex"]: dict(row) for row in base}
    report: list[list[str]] = []

    for new in overlay:
        ident = new["id_hex"]
        old = merged.get(ident)
        if old is None:
            merged[ident] = dict(new)
            report.append([ident, "adicionado", "", new["acao"], "", new["texto"], new["motivo"]])
            continue

        if old["acao"] == "usar_original" and new["acao"] == "gerar":
            report.append([
                ident, "conflito_mantido_base", old["acao"], new["acao"],
                old["texto"], old["texto"],
                "Base usa áudio original; sobreposição não aplicada automaticamente.",
            ])
            continue

        combined_reason = old["motivo"].strip()
        if new["motivo"].strip() and new["motivo"].strip() not in combined_reason:
            combined_reason = (combined_reason + " | " + new["motivo"].strip()).strip(" |")
        merged[ident] = {
            "id_hex": ident,
            "acao": new["acao"],
            "texto": new["texto"],
            "motivo": combined_reason,
        }
        status = "inalterado" if old["acao"] == new["acao"] and old["texto"] == new["texto"] else "atualizado"
        report.append([
            ident, status, old["acao"], new["acao"], old["texto"], new["texto"], combined_reason,
        ])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(["id_hex", "acao", "texto", "motivo"])
        for ident in sorted(merged, key=lambda value: int(value, 0)):
            row = merged[ident]
            writer.writerow([row["id_hex"], row["acao"], row["texto"], row["motivo"]])

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow([
            "id_hex", "status", "acao_base", "acao_overlay", "texto_base",
            "texto_final", "detalhe",
        ])
        writer.writerows(report)

    counts: dict[str, int] = {}
    for row in report:
        counts[row[1]] = counts.get(row[1], 0) + 1
    print(f"Base: {len(base)}; overlay: {len(overlay)}; consolidado: {len(merged)}")
    print("Mesclagem: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"Arquivo: {args.output}")
    print(f"Relatório: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
