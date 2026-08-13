#!/usr/bin/env python3
"""Compara dois w3speech compactos e exige alteração apenas nos IDs esperados."""

from __future__ import annotations

import argparse
import csv
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


ENTRY = struct.Struct("<10I")
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
TRAILER = struct.Struct("<fI")


@dataclass(frozen=True)
class Item:
    ident: int
    high: int
    wave_offset: int
    wave_size: int
    cr2w_offset: int
    cr2w_size: int


def exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError(f"fim inesperado: {len(data)}/{size}")
    return data


def bit6(handle) -> int:
    result = 0
    shift = 0
    index = 1
    for _ in range(20):
        value = exact(handle, 1)[0]
        if value == 128:
            return 0
        step, mask = 6, 0xFF
        if value > 127:
            step, mask = 7, 0x7F
        elif value > 63 and index == 1:
            mask = 0x3F
        result |= (value & mask) << shift
        shift += step
        index += 1
        if value < 64 or (index >= 3 and value < 128):
            return result
    raise ValueError("bit6 inválido")


def index(path: Path) -> list[Item]:
    with path.open("rb") as handle:
        if exact(handle, 4) != b"CPSW":
            raise ValueError(f"{path}: CPSW ausente")
        if U32.unpack(exact(handle, 4))[0] != 163:
            raise ValueError(f"{path}: versão incompatível")
        if U16.unpack(exact(handle, 2))[0] != 0:
            raise ValueError(f"{path}: chave inválida")
        count = bit6(handle)
        rows = []
        for _ in range(count):
            ident, high, wo, z1, ws, z2, co, z3, cs, z4 = ENTRY.unpack(
                exact(handle, ENTRY.size)
            )
            if z1 or z2 or z3 or z4:
                raise ValueError(f"{path}: reservados não nulos")
            rows.append(Item(ident, high, wo, ws, co, cs))
        if U16.unpack(exact(handle, 2))[0] != 0:
            raise ValueError(f"{path}: segunda chave inválida")
        return rows


def digest_range(handle, offset: int, size: int) -> bytes:
    digest = hashlib.sha256()
    handle.seek(offset)
    remaining = size
    while remaining:
        chunk = exact(handle, min(4 * 1024 * 1024, remaining))
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.digest()


def media(handle, item: Item) -> tuple[int, bytes, float, int]:
    handle.seek(item.wave_offset)
    size = U32.unpack(exact(handle, 4))[0]
    if size + 12 != item.wave_size:
        raise ValueError(f"tamanho inválido em 0x{item.ident:08x}")
    digest = hashlib.sha256(exact(handle, size)).digest()
    duration, kind = TRAILER.unpack(exact(handle, TRAILER.size))
    return size, digest, duration, kind


def expected_ids(directory: Path) -> set[int]:
    result = set()
    for path in directory.glob("*.wem"):
        result.add(int(path.stem, 0))
    if not result:
        raise ValueError(f"nenhum WEM esperado em {directory}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--expected-wem-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    old_items = index(args.old)
    new_items = index(args.new)
    old_keys = [(item.ident, item.high) for item in old_items]
    new_keys = [(item.ident, item.high) for item in new_items]
    if old_keys != new_keys:
        raise ValueError("ordem ou conjunto de IDs compostos divergiu")

    changed: list[dict[str, object]] = []
    cr2w_changes = 0
    with args.old.open("rb") as old_handle, args.new.open("rb") as new_handle:
        for old_item, new_item in zip(old_items, new_items):
            old_size, old_hash, old_duration, old_kind = media(old_handle, old_item)
            new_size, new_hash, new_duration, new_kind = media(new_handle, new_item)
            if old_kind != new_kind:
                raise ValueError(f"trailer divergente em 0x{old_item.ident:08x}")
            if old_item.cr2w_size != new_item.cr2w_size:
                cr2w_changes += 1
            elif old_item.cr2w_size and digest_range(
                old_handle, old_item.cr2w_offset, old_item.cr2w_size
            ) != digest_range(new_handle, new_item.cr2w_offset, new_item.cr2w_size):
                cr2w_changes += 1
            if old_hash != new_hash:
                changed.append(
                    {
                        "id": f"0x{old_item.ident:08x}",
                        "id_high": f"0x{old_item.high:08x}",
                        "wem_antigo_bytes": old_size,
                        "wem_novo_bytes": new_size,
                        "duracao_antiga": round(old_duration, 6),
                        "duracao_nova": round(new_duration, 6),
                    }
                )

    changed_ids = {int(row["id"], 0) for row in changed}
    expected = expected_ids(args.expected_wem_dir)
    if cr2w_changes:
        raise ValueError(f"CR2Ws divergentes: {cr2w_changes}")
    if changed_ids != expected:
        missing = expected - changed_ids
        extra = changed_ids - expected
        raise ValueError(
            "alterações WEM divergentes; "
            f"esperadas_sem_mudança={sorted(missing)}, extras={sorted(extra)}"
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = list(changed[0]) if changed else []
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(changed)
    print(f"Entradas comparadas: {len(old_items)}", flush=True)
    print(f"IDs WEM alterados: {len(changed_ids)}", flush=True)
    print("CR2Ws alterados: 0", flush=True)
    print(f"Relatório: {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
