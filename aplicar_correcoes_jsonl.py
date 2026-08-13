#!/usr/bin/env python3
"""Aplica correções textuais explícitas a um JSONL e pode selecionar só os IDs corrigidos."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


class CorrectionError(RuntimeError):
    pass


def read_corrections(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise CorrectionError(f"correções não encontradas: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames or not {"id_hex", "texto"}.issubset(reader.fieldnames):
            raise CorrectionError("CSV deve conter id_hex;texto")
        result: dict[str, str] = {}
        for row in reader:
            ident = (row.get("id_hex") or "").strip().lower()
            text = (row.get("texto") or "").strip()
            if not ident or not text:
                raise CorrectionError("correção com ID ou texto vazio")
            if ident in result:
                raise CorrectionError(f"ID repetido nas correções: {ident}")
            result[ident] = text
    if not result:
        raise CorrectionError("nenhuma correção encontrada")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.jsonl.is_file():
            raise CorrectionError(f"JSONL não encontrado: {args.jsonl}")
        corrections = read_corrections(args.corrections)
        output_rows: list[dict[str, object]] = []
        corrected: set[str] = set()
        with args.jsonl.open("r", encoding="utf-8-sig") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise CorrectionError(f"JSON inválido na linha {line_number}") from exc
                ident = str(payload.get("id", "")).strip().lower()
                if ident in corrections:
                    payload["text"] = corrections[ident]
                    corrected.add(ident)
                    output_rows.append(payload)
                elif not args.selection_only:
                    output_rows.append(payload)
        missing = sorted(set(corrections) - corrected)
        if missing:
            raise CorrectionError("IDs ausentes do JSONL: " + ", ".join(missing))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            for payload in output_rows:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        print(f"Correções aplicadas: {len(corrected)}")
        print(f"Linhas de saída: {len(output_rows)}")
        print(f"JSONL: {args.output}")
        return 0
    except (CorrectionError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
