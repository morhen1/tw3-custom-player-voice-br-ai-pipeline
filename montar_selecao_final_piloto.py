#!/usr/bin/env python3
"""Monta uma pasta provisória de WAVs conforme as decisões de revisão do piloto."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path


class SelectionError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--multi-dir", type=Path, required=True)
    parser.add_argument("--correction-dir", type=Path, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def require_file(directory: Path, ident: str, label: str) -> Path:
    path = directory / f"{ident}.wav"
    if not path.is_file() or path.stat().st_size <= 44:
        raise SelectionError(f"{label} ausente ou vazio: {path}")
    return path


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.decisions.is_file():
            raise SelectionError(f"decisões não encontradas: {args.decisions}")
        with args.decisions.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        if not rows:
            raise SelectionError("decisões vazias")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        args.review_dir.mkdir(parents=True, exist_ok=True)
        report_rows: list[list[str]] = []
        for row in rows:
            ident = (row.get("id_hex") or "").strip().lower()
            action = (row.get("acao_decidida") or "").strip()
            mark = (row.get("marcacao") or "").strip()
            if action == "manter_pandora_atual":
                source = require_file(args.current_dir, ident, "Pandora atual final")
                origin = "pandora_atual_final"
            elif action == "regenerar_com_texto_revisado":
                source = require_file(args.correction_dir, ident, "correção final")
                origin = "multireferencia_corrigida_final"
            elif action in {"usar_multireferencia", "usar_multireferencia_posprocessada"}:
                source = require_file(args.multi_dir, ident, "multirreferência final")
                origin = "multireferencia_final"
            else:
                raise SelectionError(f"{ident}: ação desconhecida: {action}")
            destination = args.output_dir / f"{ident}.wav"
            shutil.copy2(source, destination)

            if mark != "sem_marcacao":
                official = require_file(args.official_dir, ident, "oficial")
                current = require_file(args.current_dir, ident, "Pandora atual final")
                multi = require_file(args.multi_dir, ident, "multirreferência final")
                for number, label, item in (
                    (1, "oficial", official),
                    (2, "pandora_atual_final", current),
                    (3, "multireferencia_final", multi),
                    (4, "selecao_provisoria", destination),
                ):
                    shutil.copy2(item, args.review_dir / f"{ident}__{number}_{label}.wav")
            report_rows.append(
                [
                    ident,
                    row.get("estilo", ""),
                    row.get("texto", ""),
                    mark,
                    action,
                    origin,
                    str(source.resolve()),
                    str(destination.resolve()),
                ]
            )

        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "id_hex",
                    "estilo",
                    "texto",
                    "marcacao",
                    "acao_decidida",
                    "origem_selecionada",
                    "arquivo_origem",
                    "arquivo_destino",
                ]
            )
            writer.writerows(report_rows)
        print(f"Falas selecionadas: {len(report_rows)}")
        print(f"Casos separados para revisão: {sum(row[3] != 'sem_marcacao' for row in report_rows)}")
        print(f"Seleção provisória: {args.output_dir}")
        print(f"Revisão: {args.review_dir}")
        print(f"Relatório: {args.report}")
        return 0
    except (SelectionError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
