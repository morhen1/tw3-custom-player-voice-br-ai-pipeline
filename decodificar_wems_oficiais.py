#!/usr/bin/env python3
"""Decodifica uma pasta de WEMs oficiais para WAV PCM com vgmstream-cli."""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


WEM_RE = re.compile(r"^0x[0-9a-fA-F]{8}\.wem$")


class DecodeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DecodeRow:
    ident: str
    status: str
    source: str
    output: str
    duration_s: str = ""
    channels: str = ""
    sample_rate: str = ""
    sample_width_bits: str = ""
    detail: str = ""


def validate_pcm_wav(path: Path) -> tuple[float, int, int, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_rate = handle.getframerate()
            sample_width = handle.getsampwidth()
            frames = handle.getnframes()
            compression = handle.getcomptype()
    except (OSError, EOFError, wave.Error) as exc:
        raise DecodeError(f"WAV inválido: {path}: {exc}") from exc
    if compression != "NONE":
        raise DecodeError(f"WAV não PCM: {path} ({compression})")
    if channels not in (1, 2) or sample_rate < 8_000 or sample_width not in (1, 2, 3, 4):
        raise DecodeError(
            f"formato WAV inesperado: {channels}ch/{sample_rate}Hz/{sample_width * 8}bit"
        )
    if frames < 1:
        raise DecodeError(f"WAV vazio: {path}")
    return frames / sample_rate, channels, sample_rate, sample_width * 8


def write_report(path: Path, rows: Sequence[DecodeRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "id_hex",
                "status",
                "wem_origem",
                "wav_saida",
                "duracao_s",
                "canais",
                "sample_rate",
                "bits",
                "detalhe",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.ident,
                    row.status,
                    row.source,
                    row.output,
                    row.duration_s,
                    row.channels,
                    row.sample_rate,
                    row.sample_width_bits,
                    row.detail,
                ]
            )
    os.replace(partial, path)


def decode_directory(
    executable: Path,
    input_dir: Path,
    output_dir: Path,
    report_path: Path,
    *,
    force: bool = False,
) -> tuple[list[DecodeRow], list[str]]:
    if not executable.is_file():
        raise DecodeError(f"vgmstream-cli não encontrado: {executable}")
    if not input_dir.is_dir():
        raise DecodeError(f"pasta WEM não encontrada: {input_dir}")
    wems = sorted(
        path for path in input_dir.iterdir() if path.is_file() and WEM_RE.fullmatch(path.name)
    )
    if not wems:
        raise DecodeError(f"nenhum WEM hexadecimal encontrado em {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[DecodeRow] = []
    errors: list[str] = []
    for index, source in enumerate(wems, start=1):
        ident = source.stem.lower()
        destination = output_dir / f"{ident}.wav"
        temporary = output_dir / f"{ident}.partial.wav"
        try:
            if destination.exists() and not force:
                raise DecodeError(f"saída já existe: {destination}")
            temporary.unlink(missing_ok=True)
            completed = subprocess.run(
                [str(executable), "-i", "-o", str(temporary), str(source)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            output_text = completed.stdout.decode("utf-8", errors="replace").strip()
            if completed.returncode != 0:
                raise DecodeError(
                    f"vgmstream retornou {completed.returncode}: {output_text[-800:]}"
                )
            duration, channels, sample_rate, bits = validate_pcm_wav(temporary)
            os.replace(temporary, destination)
            rows.append(
                DecodeRow(
                    ident=ident,
                    status="ok",
                    source=str(source),
                    output=str(destination),
                    duration_s=f"{duration:.6f}",
                    channels=str(channels),
                    sample_rate=str(sample_rate),
                    sample_width_bits=str(bits),
                )
            )
            if index == 1 or index == len(wems) or index % 25 == 0:
                print(f"Progresso: {index}/{len(wems)}")
        except (DecodeError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            rows.append(
                DecodeRow(
                    ident=ident,
                    status="erro",
                    source=str(source),
                    output=str(destination),
                    detail=str(exc),
                )
            )
            errors.append(f"{ident}: {exc}")

    write_report(report_path, rows)
    return rows, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decodifica WEMs oficiais para WAV PCM usando vgmstream-cli."
    )
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows, errors = decode_directory(
            args.executable.resolve(),
            args.input.resolve(),
            args.output.resolve(),
            args.report.resolve(),
            force=args.force,
        )
        valid = sum(row.status == "ok" for row in rows)
        print(f"WAVs válidos: {valid}/{len(rows)}")
        print(f"Relatório: {args.report.resolve()}")
        if errors:
            print(f"ERRO: {len(errors)} item(ns) falharam", file=sys.stderr)
            return 1
        print("Decodificação concluída e validada.")
        return 0
    except (DecodeError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
