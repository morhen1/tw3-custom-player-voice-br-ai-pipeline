#!/usr/bin/env python3
"""Extrai duração e canais originais dos brpc.w3speech do TW3 4.04."""

from __future__ import annotations

import argparse
import csv
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


MAGIC = b"CPSW"
VERSION = 163
ENTRY = struct.Struct("<10I")
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
FMT = struct.Struct("<HHIIHH")
OFFICIAL_DLC_RE = re.compile(r"^(?:bob|ep1|dlc\d+)$", re.IGNORECASE)


class SpeechError(RuntimeError):
    pass


@dataclass(frozen=True)
class Metadata:
    duration: float
    channels: int
    sample_rate: int
    codec: str
    sources: tuple[str, ...]


def read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise SpeechError("fim inesperado do arquivo")
    return data


def read_bit6(handle: BinaryIO) -> int:
    result = 0
    shift = 0
    index = 1
    for _ in range(20):
        value = read_exact(handle, 1)[0]
        if value == 128:
            return 0
        mask, step = 0xFF, 6
        if value > 127:
            mask, step = 0x7F, 7
        elif value > 63 and index == 1:
            mask = 0x3F
        result |= (value & mask) << shift
        shift += step
        index += 1
        if value < 64 or (index >= 3 and value < 128):
            return result
    raise SpeechError("contador bit6 inválido")


def read_ids(path: Path) -> set[int]:
    result: set[int] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip() or raw.lstrip().startswith(";"):
                continue
            token = raw.split("|", 1)[0].strip()
            if not token.isdecimal():
                continue
            ident = int(token)
            if not 0 <= ident <= 0xFFFFFFFF:
                raise SpeechError(f"linha {line_number}: ID fora de uint32")
            result.add(ident)
    if not result:
        raise SpeechError(f"nenhum ID encontrado em {path}")
    return result


def discover(game_root: Path) -> list[Path]:
    result: set[Path] = set()
    result.update((game_root / "content").glob("content*/brpc.w3speech"))
    dlc = game_root / "dlc"
    if dlc.is_dir():
        for child in dlc.iterdir():
            if child.is_dir() and OFFICIAL_DLC_RE.fullmatch(child.name):
                result.update(child.rglob("brpc.w3speech"))
    paths = sorted(path.resolve() for path in result if path.is_file())
    if not paths:
        raise SpeechError(f"nenhum brpc.w3speech oficial encontrado em {game_root}")
    return paths


def parse_wem(data: bytes, label: str) -> tuple[float, int, int, str]:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise SpeechError(f"{label}: RIFF/WAVE ausente")
    if U32.unpack_from(data, 4)[0] + 8 != len(data):
        raise SpeechError(f"{label}: tamanho RIFF divergente")
    pos = 12
    fmt: tuple[int, int, int, int, int, int] | None = None
    fmt_size = 0
    data_size: int | None = None
    while pos + 8 <= len(data):
        chunk = data[pos:pos + 4]
        size = U32.unpack_from(data, pos + 4)[0]
        payload = pos + 8
        end = payload + size
        if end > len(data):
            raise SpeechError(f"{label}: chunk fora dos limites")
        if chunk == b"fmt ":
            if size < FMT.size:
                raise SpeechError(f"{label}: fmt pequeno demais")
            fmt = FMT.unpack_from(data, payload)
            fmt_size = size
        elif chunk == b"data":
            data_size = size
        pos = end + (size & 1)
    if fmt is None or data_size is None:
        raise SpeechError(f"{label}: fmt/data ausente")
    tag, channels, rate, avg_bps, _align, _bits = fmt
    if avg_bps <= 0 or channels not in {1, 2}:
        raise SpeechError(f"{label}: metadados de áudio inválidos")
    if tag == 0x3041 and fmt_size == 36:
        codec = "wem-opus"
    elif tag == 0xFFFF and fmt_size == 66:
        codec = "wwise-vorbis"
    else:
        codec = f"0x{tag:04x}/fmt{fmt_size}"
    return data_size / avg_bps, channels, rate, codec


def source_label(path: Path) -> str:
    parent = path.parent.parent
    return parent.name if parent.name.lower() != "content" else path.parent.name


def index_archive(path: Path, targets: set[int]) -> dict[int, list[tuple[float, int, int, str, str]]]:
    size = path.stat().st_size
    matches: dict[int, list[tuple[float, int, int, str, str]]] = {}
    ignored_occurrences = 0
    with path.open("rb") as handle:
        if read_exact(handle, 4) != MAGIC:
            raise SpeechError(f"{path}: assinatura CPSW ausente")
        version = U32.unpack(read_exact(handle, 4))[0]
        if version != VERSION:
            raise SpeechError(f"{path}: versão {version}; esperado {VERSION}")
        key1 = U16.unpack(read_exact(handle, 2))[0]
        count = read_bit6(handle)
        rows = [ENTRY.unpack(read_exact(handle, ENTRY.size)) for _ in range(count)]
        key2 = U16.unpack(read_exact(handle, 2))[0]
        if key1 or key2:
            raise SpeechError(f"{path}: pacote não é br/brpc")
        for row in rows:
            ident, _high, wave_offset, _z1, wave_size, _z2, *_rest = row
            if ident not in targets:
                continue
            if wave_size < 12 or wave_offset + wave_size > size:
                ignored_occurrences += 1
                continue
            handle.seek(wave_offset)
            wem_size = U32.unpack(read_exact(handle, 4))[0]
            if wem_size + 12 != wave_size:
                ignored_occurrences += 1
                continue
            data = read_exact(handle, wem_size)
            try:
                duration, channels, rate, codec = parse_wem(
                    data, f"{path}:0x{ident:08x}"
                )
            except SpeechError:
                ignored_occurrences += 1
                continue
            matches.setdefault(ident, []).append(
                (duration, channels, rate, codec, source_label(path))
            )
    if ignored_occurrences:
        print(
            f"  AVISO: {ignored_occurrences} ocorrência(s) sem mídia válida ignorada(s)",
            file=sys.stderr,
        )
    return matches


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-missing", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        targets = read_ids(args.lines)
        paths = discover(args.game_root.resolve())
        found: dict[int, list[tuple[float, int, int, str, str]]] = {}
        print(f"IDs procurados: {len(targets)}; pacotes oficiais: {len(paths)}")
        for index, path in enumerate(paths, start=1):
            print(f"[{index}/{len(paths)}] {path}")
            for ident, rows in index_archive(path, targets).items():
                found.setdefault(ident, []).extend(rows)

        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([
                "id_hex", "duracao_segundos", "canais", "sample_rate",
                "codec", "pacotes", "status",
            ])
            for ident in sorted(targets):
                candidates = found.get(ident, [])
                if not candidates:
                    writer.writerow([f"0x{ident:08x}", "", "", "", "", "", "ausente"])
                    errors.append(f"0x{ident:08x}: ausente")
                    continue
                first = candidates[0]
                divergent = any(
                    abs(row[0] - first[0]) > 0.02 or row[1:4] != first[1:4]
                    for row in candidates[1:]
                )
                status = "divergente" if divergent else "ok"
                writer.writerow([
                    f"0x{ident:08x}", f"{first[0]:.6f}", first[1], first[2],
                    first[3], ",".join(sorted({row[4] for row in candidates})), status,
                ])
                if divergent:
                    errors.append(f"0x{ident:08x}: metadados divergentes")
        print(f"Encontrados: {len(found)}/{len(targets)}; relatório: {output}")
        if errors and not args.allow_missing:
            preview = ", ".join(errors[:10])
            raise SpeechError(f"{len(errors)} problema(s): {preview}")
        return 0
    except (SpeechError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
