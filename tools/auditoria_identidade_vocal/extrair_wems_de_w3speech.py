#!/usr/bin/env python3
"""Extrai WEMs selecionados de um brpc.w3speech compacto validado."""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
from pathlib import Path


ENTRY = struct.Struct("<10I")
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")


def read_exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError(f"fim inesperado: {len(data)}/{size} bytes")
    return data


def read_bit6(handle) -> int:
    result = 0
    shift = 0
    index = 1
    for _ in range(20):
        value = read_exact(handle, 1)[0]
        if value == 128:
            return 0
        step = 6
        mask = 0xFF
        if value > 127:
            mask = 0x7F
            step = 7
        elif value > 63 and index == 1:
            mask = 0x3F
        result |= (value & mask) << shift
        shift += step
        index += 1
        if value < 64 or (index >= 3 and value < 128):
            return result
    raise ValueError("contador bit6 inválido")


def load_ids(path: Path) -> set[int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    if not rows or "id" not in rows[0]:
        raise ValueError("CSV deve possuir a coluna id")
    return {int(row["id"], 0) for row in rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--ids-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    wanted = load_ids(args.ids_csv)
    found: dict[int, list[bytes]] = {ident: [] for ident in wanted}
    with args.archive.open("rb") as handle:
        if read_exact(handle, 4) != b"CPSW":
            raise ValueError("assinatura CPSW ausente")
        version = U32.unpack(read_exact(handle, 4))[0]
        if version != 163:
            raise ValueError(f"versão incompatível: {version}")
        if U16.unpack(read_exact(handle, 2))[0] != 0:
            raise ValueError("chave de idioma inesperada")
        count = read_bit6(handle)
        entries = [ENTRY.unpack(read_exact(handle, ENTRY.size)) for _ in range(count)]
        if U16.unpack(read_exact(handle, 2))[0] != 0:
            raise ValueError("segunda chave de idioma inesperada")

        for entry in entries:
            ident, _high, wave_offset, z1, wave_size, z2, _cr2w, z3, _cs, z4 = entry
            if ident not in wanted:
                continue
            if z1 or z2 or z3 or z4 or wave_size < 12:
                raise ValueError(f"entrada inválida em 0x{ident:08x}")
            handle.seek(wave_offset)
            wem_size = U32.unpack(read_exact(handle, 4))[0]
            if wem_size + 12 != wave_size:
                raise ValueError(f"tamanho WEM divergente em 0x{ident:08x}")
            data = read_exact(handle, wem_size)
            if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise ValueError(f"WEM inválido em 0x{ident:08x}")
            found[ident].append(data)

    missing = [ident for ident, values in found.items() if not values]
    if missing:
        raise ValueError(
            "IDs ausentes: " + ", ".join(f"0x{ident:08x}" for ident in sorted(missing))
        )

    args.output.mkdir(parents=True, exist_ok=True)
    for ident in sorted(found):
        variants = found[ident]
        hashes = {hashlib.sha256(data).digest() for data in variants}
        if len(hashes) != 1:
            raise ValueError(f"duplicatas WEM divergentes em 0x{ident:08x}")
        destination = args.output / f"0x{ident:08x}.wem"
        destination.write_bytes(variants[0])
        print(
            f"0x{ident:08x}: {len(variants)} ocorrência(s), "
            f"{len(variants[0])} bytes",
            flush=True,
        )
    print(f"Extraídos: {len(found)}/{len(wanted)}", flush=True)
    print(f"Saída: {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
