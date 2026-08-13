#!/usr/bin/env python3
"""Seleciona do JSONL somente IDs marcados para gerar em um CSV de correções."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


class SelectionError(RuntimeError):
    pass


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if len(token) != 10 or not token.startswith("0x"):
        raise SelectionError(f"ID inválido: {value}")
    try:
        int(token[2:], 16)
    except ValueError as exc:
        raise SelectionError(f"ID inválido: {value}") from exc
    return token


def read_generate_ids(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise SelectionError(f"{path}: cabeçalho deve conter id_hex;acao")
        result: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            ident = normalize_id(row.get("id_hex") or "")
            action = (row.get("acao") or "").strip().lower()
            if action not in {"gerar", "usar_original"}:
                raise SelectionError(f"{path}, linha {line_number}: ação inválida: {action}")
            if action == "gerar":
                if ident in result:
                    raise SelectionError(f"ID repetido: {ident}")
                result.add(ident)
    if not result:
        raise SelectionError("nenhum ID marcado para gerar")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        wanted = read_generate_ids(args.corrections)
        selected: dict[str, dict[str, object]] = {}
        with args.jsonl.open("r", encoding="utf-8-sig") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise SelectionError(f"JSON inválido na linha {line_number}") from exc
                ident = normalize_id(str(payload.get("id", "")))
                if ident not in wanted:
                    continue
                if ident in selected:
                    raise SelectionError(f"ID repetido no JSONL: {ident}")
                payload["id"] = ident
                payload.pop("duration", None)
                selected[ident] = payload

        missing = sorted(wanted - set(selected), key=lambda value: int(value, 0))
        if missing:
            raise SelectionError(
                f"{len(missing)} ID(s) ausente(s) do JSONL: " + ", ".join(missing[:10])
            )

        ordered = [selected[ident] for ident in sorted(selected, key=lambda value: int(value, 0))]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            for payload in ordered:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "texto", "ref_audio", "possui_duration"])
            for payload in ordered:
                writer.writerow([
                    payload["id"], payload.get("text", ""), payload.get("ref_audio", ""),
                    "sim" if "duration" in payload else "não",
                ])
        print(f"Selecionadas: {len(ordered)} fala(s)")
        print(f"JSONL: {args.output}")
        print(f"Relatório: {args.report}")
        return 0
    except (OSError, SelectionError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
