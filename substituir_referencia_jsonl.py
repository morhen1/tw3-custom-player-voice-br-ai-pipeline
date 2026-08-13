#!/usr/bin/env python3
"""Substitui áudio e texto de referência de um JSONL do OmniVoice."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ref-audio", type=Path, required=True)
    parser.add_argument("--ref-text", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.input.is_file():
        print(f"ERRO: JSONL não encontrado: {args.input}", file=sys.stderr)
        return 2
    if not args.ref_audio.is_file():
        print(f"ERRO: áudio de referência não encontrado: {args.ref_audio}", file=sys.stderr)
        return 2
    if not args.ref_text.strip():
        print("ERRO: texto de referência vazio", file=sys.stderr)
        return 2

    rows: list[dict[str, object]] = []
    try:
        with args.input.open("r", encoding="utf-8-sig") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    print(
                        f"ERRO: JSON inválido em {args.input}, linha {line_number}: {exc}",
                        file=sys.stderr,
                    )
                    return 2
                payload["ref_audio"] = str(args.ref_audio.resolve())
                payload["ref_text"] = args.ref_text.strip()
                rows.append(payload)
    except OSError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print(f"ERRO: JSONL vazio: {args.input}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for payload in rows:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print(f"JSONL: {args.output} ({len(rows)} fala(s))")
    print(f"Referência: {args.ref_audio.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
