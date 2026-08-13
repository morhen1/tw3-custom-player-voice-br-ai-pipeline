#!/usr/bin/env python3
"""Consolida marcações em nomes de WAV e a aprovação implícita dos não marcados."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


class AnnotationError(RuntimeError):
    pass


FILE_RE = re.compile(
    r"(?P<id>0x[0-9a-f]{8})__(?P<variant>[123]_.+?)(?:_(?P<tag>falha|melhor|tempo))?\.wav$",
    re.IGNORECASE,
)

ACTION_BY_TAG = {
    "falha": "regenerar_com_texto_revisado",
    "melhor": "manter_pandora_atual",
    "tempo": "usar_multireferencia_posprocessada",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--comparison-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.manifest.is_file():
            raise AnnotationError(f"manifesto não encontrado: {args.manifest}")
        if not args.comparison_dir.is_dir():
            raise AnnotationError(f"pasta não encontrada: {args.comparison_dir}")
        with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle, delimiter=";"))
        if not source_rows:
            raise AnnotationError("manifesto vazio")

        annotations: dict[str, list[tuple[str, str, str]]] = {}
        for path in args.comparison_dir.rglob("*.wav"):
            match = FILE_RE.search(path.name)
            if not match or not match.group("tag"):
                continue
            ident = match.group("id").lower()
            annotations.setdefault(ident, []).append(
                (match.group("tag").lower(), match.group("variant"), str(path.resolve()))
            )

        output_rows: list[list[str]] = []
        for row in source_rows:
            ident = (row.get("id_hex") or "").strip().lower()
            style = (row.get("estilo") or "").strip()
            text = (row.get("texto") or "").strip()
            marked = annotations.get(ident, [])
            tags = {item[0] for item in marked}
            if len(tags) > 1:
                raise AnnotationError(f"marcações conflitantes para {ident}: {sorted(tags)}")
            if marked:
                tag, variant, marked_file = marked[0]
                action = ACTION_BY_TAG[tag]
                note = {
                    "falha": "defeito de geração ou português; requer nova escuta",
                    "melhor": "pela regra do usuário, conservar a Pandora atual",
                    "tempo": "boa atuação; comparar novamente após pós-processamento",
                }[tag]
            else:
                tag = "sem_marcacao"
                variant = "3_multireferencia"
                marked_file = ""
                action = "usar_multireferencia"
                note = "multirreferência aprovada implicitamente pelo usuário"
            output_rows.append(
                [ident, style, text, tag, variant, action, note, marked_file]
            )

        unknown = sorted(set(annotations) - {row[0] for row in output_rows})
        if unknown:
            raise AnnotationError("IDs marcados ausentes do manifesto: " + ", ".join(unknown))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "id_hex",
                    "estilo",
                    "texto",
                    "marcacao",
                    "variante_marcada",
                    "acao_decidida",
                    "observacao",
                    "arquivo_marcado",
                ]
            )
            writer.writerows(output_rows)
        counts: dict[str, int] = {}
        for row in output_rows:
            counts[row[5]] = counts.get(row[5], 0) + 1
        print(f"Falas consolidadas: {len(output_rows)}")
        print("Ações: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
        print(f"Relatório: {args.output}")
        return 0
    except (AnnotationError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
