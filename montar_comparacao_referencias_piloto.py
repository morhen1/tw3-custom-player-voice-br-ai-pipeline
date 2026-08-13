#!/usr/bin/env python3
"""Organiza áudio oficial, Pandora atual e candidata multirreferência por estilo."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path


class ComparisonError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser


def require_wav(directory: Path, ident: str, label: str) -> Path:
    path = directory / f"{ident}.wav"
    if not path.is_file() or path.stat().st_size <= 44:
        raise ComparisonError(f"{label} ausente ou vazio: {path}")
    return path


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.input.is_file():
            raise ComparisonError(f"CSV não encontrado: {args.input}")
        with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            required = {"id_hex", "texto_atual", "estilo_id"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ComparisonError("CSV deve conter id_hex;texto_atual;estilo_id")
            rows = list(reader)
        if not rows:
            raise ComparisonError("CSV vazio")

        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_rows: list[list[str]] = []
        playlists: dict[str, list[str]] = defaultdict(list)
        style_index: dict[str, int] = defaultdict(int)
        for row in rows:
            ident = (row.get("id_hex") or "").strip().lower()
            style = (row.get("estilo_id") or "").strip()
            text = (row.get("texto_atual") or "").strip()
            if not ident or not style or not text:
                raise ComparisonError(f"linha incompleta: {row}")
            official = require_wav(args.official_dir, ident, "oficial")
            current = require_wav(args.current_dir, ident, "Pandora atual")
            candidate = require_wav(args.candidate_dir, ident, "candidata")
            style_index[style] += 1
            number = style_index[style]
            style_dir = args.output_dir / style
            style_dir.mkdir(parents=True, exist_ok=True)
            prefix = f"{number:02d}_{ident}"
            destinations = {
                "oficial": style_dir / f"{prefix}__1_oficial.wav",
                "atual": style_dir / f"{prefix}__2_pandora_atual.wav",
                "candidata": style_dir / f"{prefix}__3_multireferencia.wav",
            }
            for source, destination in (
                (official, destinations["oficial"]),
                (current, destinations["atual"]),
                (candidate, destinations["candidata"]),
            ):
                shutil.copy2(source, destination)
                playlists[style].append(destination.name)
            warning = ""
            if style == "pergunta_cautelosa" and ident == "0x00083750":
                warning = "a própria fala foi usada como referência candidata; validar depois com outra pergunta"
            manifest_rows.append(
                [
                    style,
                    ident,
                    text,
                    str(destinations["oficial"]),
                    str(destinations["atual"]),
                    str(destinations["candidata"]),
                    warning,
                ]
            )

        for style, entries in playlists.items():
            playlist = args.output_dir / style / "ordem_audicao.m3u8"
            playlist.write_text("#EXTM3U\n" + "\n".join(entries) + "\n", encoding="utf-8")

        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "estilo",
                    "id_hex",
                    "texto",
                    "audio_oficial",
                    "pandora_atual",
                    "multireferencia_candidata",
                    "observacao",
                ]
            )
            writer.writerows(manifest_rows)
        print(f"Falas organizadas: {len(manifest_rows)}")
        print(f"Estilos: {len(playlists)}")
        print(f"Pasta: {args.output_dir}")
        print(f"Manifesto: {args.manifest}")
        return 0
    except (ComparisonError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
