#!/usr/bin/env python3
"""Monta um brpc.w3speech compacto com substituições de fala do TW3 4.04.

O utilitário procura cada ID WEM nos pacotes brasileiros do jogo-base e dos
DLCs, copia o CR2W (lipsync) correspondente sem modificá-lo e grava somente as
entradas substituídas. Os arquivos originais do jogo nunca são alterados.

Primeiro teste recomendado:

    py -3 montar_brpc_w3speech_compacto_v4.py --only-id 0x000f4f9c

Sem ``--output`` o comando faz apenas a auditoria e cria um relatório CSV.
Depois de conferir o relatório, informe ``--output`` para montar o pacote.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence


MAGIC = b"CPSW"
SUPPORTED_VERSION = 163
ENTRY_STRUCT = struct.Struct("<10I")
U16 = struct.Struct("<H")
U32 = struct.Struct("<I")
WAVE_TRAILER = struct.Struct("<fI")
FMT_BASE = struct.Struct("<HHIIHH")
COPY_CHUNK = 4 * 1024 * 1024
WEM_RE = re.compile(r"^(?:0x)?([0-9a-fA-F]{1,8})\.wem$", re.IGNORECASE)
OFFICIAL_DLC_RE = re.compile(r"^(?:bob|ep1|dlc\d+)$", re.IGNORECASE)

class FormatError(RuntimeError):
    """Arquivo ausente, incompatível ou estruturalmente inválido."""


@dataclass(frozen=True)
class Entry:
    ident: int
    ident_high: int
    wave_offset: int
    zero1: int
    wave_size: int
    zero2: int
    cr2w_offset: int
    zero3: int
    cr2w_size: int
    zero4: int

    @classmethod
    def unpack(cls, data: bytes) -> "Entry":
        return cls(*ENTRY_STRUCT.unpack(data))

    def pack(self) -> bytes:
        return ENTRY_STRUCT.pack(
            self.ident,
            self.ident_high,
            self.wave_offset,
            self.zero1,
            self.wave_size,
            self.zero2,
            self.cr2w_offset,
            self.zero3,
            self.cr2w_size,
            self.zero4,
        )


@dataclass(frozen=True)
class Archive:
    path: Path
    version: int
    key1: int
    key2: int
    entries: tuple[Entry, ...]
    file_size: int


@dataclass(frozen=True)
class WemInfo:
    size: int
    format_tag: int
    fmt_size: int
    channels: int
    sample_rate: int
    avg_bytes_per_sec: int
    data_size: int
    duration: float
    chunks: tuple[str, ...]

    @property
    def family(self) -> str:
        if self.format_tag == 0x3041 and self.fmt_size == 36:
            return "wem-opus"
        if self.format_tag == 0xFFFF and self.fmt_size == 66:
            return "wwise-vorbis"
        if self.format_tag == 0xFFFE:
            return "pcm"
        return f"unknown-0x{self.format_tag:04x}-fmt{self.fmt_size}"


@dataclass(frozen=True)
class Location:
    source_index: int
    entry_index: int
    archive: Archive
    entry: Entry


@dataclass(frozen=True)
class Selection:
    location: Location
    replacement: Path
    old_wem: WemInfo
    new_wem: WemInfo
    trailer_kind: int

    @property
    def ident(self) -> int:
        return self.location.entry.ident

    @property
    def duration_delta_pct(self) -> float:
        if not self.old_wem.duration:
            return 0.0
        return (self.new_wem.duration / self.old_wem.duration - 1.0) * 100.0


@dataclass(frozen=True)
class ReportRow:
    ident: int
    status: str
    source: str = ""
    old_codec: str = ""
    new_codec: str = ""
    old_channels: str = ""
    new_channels: str = ""
    old_rate: str = ""
    new_rate: str = ""
    old_duration: str = ""
    new_duration: str = ""
    delta_pct: str = ""
    cr2w_size: str = ""
    detail: str = ""


@dataclass(frozen=True)
class OriginalCandidate:
    location: Location
    wem: WemInfo
    trailer_kind: int
    cr2w_hash: bytes


def parse_id(value: str) -> int:
    try:
        ident = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ID inválido: {value}") from exc
    if not 0 <= ident <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError(f"ID fora de uint32: {value}")
    return ident


def read_exact(handle: BinaryIO, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise FormatError(
            f"fim inesperado: esperados {size} bytes, recebidos {len(data)}"
        )
    return data


def read_bit6(handle: BinaryIO) -> int:
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
    raise FormatError("contador bit6 excessivamente longo")


def encode_bit6(value: int) -> bytes:
    if value < 0:
        raise ValueError("contador negativo")
    if value == 0:
        return b"\x80"
    first = value & 0x3F
    value >>= 6
    if value == 0:
        return bytes([first])
    encoded = bytearray([first | 0x40])
    while value:
        part = value & 0x7F
        value >>= 7
        if value:
            part |= 0x80
        encoded.append(part)
    return bytes(encoded)


def parse_archive(
    path: Path, validate_ids: set[int] | None = None
) -> Archive:
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        if read_exact(handle, 4) != MAGIC:
            raise FormatError(f"{path}: assinatura CPSW ausente")
        version = U32.unpack(read_exact(handle, 4))[0]
        if version != SUPPORTED_VERSION:
            raise FormatError(
                f"{path}: versão {version}; esperado {SUPPORTED_VERSION}"
            )
        key1 = U16.unpack(read_exact(handle, 2))[0]
        count = read_bit6(handle)
        entries = tuple(
            Entry.unpack(read_exact(handle, ENTRY_STRUCT.size)) for _ in range(count)
        )
        key2 = U16.unpack(read_exact(handle, 2))[0]
        header_end = handle.tell()

    if (key1 << 16) | key2:
        raise FormatError(f"{path}: pacote não é br/brpc (chave de idioma não zero)")
    seen: set[tuple[int, int]] = set()
    for entry in entries:
        composite_id = (entry.ident, entry.ident_high)
        if composite_id in seen:
            raise FormatError(
                f"{path}: ID composto duplicado "
                f"0x{entry.ident_high:08x}:0x{entry.ident:08x}"
            )
        seen.add(composite_id)
        if entry.zero1 or entry.zero2 or entry.zero3 or entry.zero4:
            raise FormatError(f"{path}: reservados não nulos em 0x{entry.ident:08x}")
        # Pacotes oficiais podem conter entradas especiais/sem mídia que não
        # interessam ao personagem selecionado. Só exigimos WEM e CR2W físicos
        # válidos para IDs que efetivamente serão copiados. Nos pacotes
        # compactos gerados por nós, validate_ids=None valida todas as entradas.
        if validate_ids is not None and entry.ident not in validate_ids:
            continue
        if entry.wave_size < 12 or entry.wave_offset + entry.wave_size > file_size:
            raise FormatError(
                f"{path}: WEM fora dos limites em 0x{entry.ident:08x} "
                f"(offset={entry.wave_offset}, tamanho={entry.wave_size}, "
                f"arquivo={file_size})"
            )
        if entry.wave_offset < header_end:
            raise FormatError(f"{path}: WEM sobrepõe o cabeçalho em 0x{entry.ident:08x}")
        wave_end = entry.wave_offset + entry.wave_size
        if entry.cr2w_size:
            if entry.cr2w_offset < wave_end:
                raise FormatError(f"{path}: CR2W sobrepõe WEM em 0x{entry.ident:08x}")
            if entry.cr2w_offset + entry.cr2w_size > file_size:
                raise FormatError(f"{path}: CR2W fora dos limites em 0x{entry.ident:08x}")
    return Archive(path, version, key1, key2, entries, file_size)


def parse_wem_bytes(data: bytes, label: str) -> WemInfo:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise FormatError(f"{label}: assinatura RIFF/WAVE ausente")
    declared = U32.unpack_from(data, 4)[0] + 8
    if declared != len(data):
        raise FormatError(
            f"{label}: RIFF declara {declared} bytes; possui {len(data)}"
        )
    pos = 12
    fmt: tuple[int, int, int, int, int, int] | None = None
    fmt_size = 0
    data_size: int | None = None
    chunks: list[str] = []
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        size = U32.unpack_from(data, pos + 4)[0]
        payload = pos + 8
        end = payload + size
        if end > len(data):
            raise FormatError(f"{label}: chunk {chunk_id!r} excede o arquivo")
        chunks.append(chunk_id.decode("ascii", errors="replace"))
        if chunk_id == b"fmt ":
            if size < FMT_BASE.size:
                raise FormatError(f"{label}: fmt pequeno demais")
            fmt = FMT_BASE.unpack_from(data, payload)
            fmt_size = size
        elif chunk_id == b"data":
            data_size = size
        pos = end + (size & 1)
    if fmt is None or data_size is None:
        raise FormatError(f"{label}: chunks fmt/data ausentes")
    format_tag, channels, rate, avg_bps, _align, _bits = fmt
    if avg_bps <= 0:
        raise FormatError(f"{label}: taxa média inválida")
    return WemInfo(
        len(data),
        format_tag,
        fmt_size,
        channels,
        rate,
        avg_bps,
        data_size,
        data_size / avg_bps,
        tuple(chunks),
    )


def read_original_candidate(location: Location) -> OriginalCandidate:
    """Lê WEM e CR2W em uma abertura e cria a impressão da ocorrência."""
    archive = location.archive
    entry = location.entry
    digest = hashlib.sha256()
    with archive.path.open("rb") as handle:
        handle.seek(entry.wave_offset)
        size = U32.unpack(read_exact(handle, 4))[0]
        if size + 12 != entry.wave_size:
            raise FormatError(
                f"{archive.path}: tamanho WEM divergente em 0x{entry.ident:08x}"
            )
        data = read_exact(handle, size)
        duration, trailer_kind = WAVE_TRAILER.unpack(
            read_exact(handle, WAVE_TRAILER.size)
        )
        if entry.cr2w_size:
            handle.seek(entry.cr2w_offset)
            remaining = entry.cr2w_size
            while remaining:
                chunk = read_exact(handle, min(COPY_CHUNK, remaining))
                digest.update(chunk)
                remaining -= len(chunk)
    info = parse_wem_bytes(data, f"{archive.path}:0x{entry.ident:08x}")
    if abs(duration - info.duration) > 0.02:
        raise FormatError(
            f"{archive.path}: duração auxiliar divergente em 0x{entry.ident:08x}"
        )
    return OriginalCandidate(location, info, trailer_kind, digest.digest())


def candidate_differences(candidates: Sequence[OriginalCandidate]) -> list[str]:
    """Lista os campos que mudam entre ocorrências do mesmo ID baixo."""
    if not candidates:
        return ["sem_candidatos"]
    first = candidates[0]
    differences: set[str] = set()
    for candidate in candidates[1:]:
        if candidate.location.entry.ident_high != first.location.entry.ident_high:
            differences.add("id_high")
        if candidate.wem.family != first.wem.family:
            differences.add("codec")
        if candidate.wem.channels != first.wem.channels:
            differences.add("canais")
        if candidate.wem.sample_rate != first.wem.sample_rate:
            differences.add("sample_rate")
        if abs(candidate.wem.duration - first.wem.duration) > 0.02:
            differences.add("duração")
        if candidate.trailer_kind != first.trailer_kind:
            differences.add("trailer_kind")
        if candidate.location.entry.cr2w_size != first.location.entry.cr2w_size:
            differences.add("tamanho_CR2W")
        if candidate.cr2w_hash != first.cr2w_hash:
            differences.add("conteúdo_CR2W")
    return sorted(differences)


def candidate_summary(candidate: OriginalCandidate) -> str:
    source = candidate.location.archive.path.parent.parent.name
    if source.lower() == "content":
        source = candidate.location.archive.path.parent.name
    return (
        f"{source}: high=0x{candidate.location.entry.ident_high:08x}, "
        f"trailer=0x{candidate.trailer_kind:08x}, "
        f"{candidate.wem.family}/{candidate.wem.channels}ch/"
        f"{candidate.wem.sample_rate}Hz/{candidate.wem.duration:.6f}s, "
        f"CR2W={candidate.location.entry.cr2w_size}:"
        f"{candidate.cr2w_hash.hex()[:12]}"
    )


def scan_wems(directory: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file():
            continue
        match = WEM_RE.fullmatch(path.name)
        if not match:
            continue
        ident = int(match.group(1), 16)
        if ident in found:
            raise FormatError(
                f"dois WEMs representam 0x{ident:08x}: "
                f"{found[ident].name} e {path.name}"
            )
        found[ident] = path
    if not found:
        raise FormatError(f"nenhum WEM hexadecimal encontrado em {directory}")
    return found


def natural_path_key(path: Path) -> tuple[object, ...]:
    parts: list[object] = []
    for part in re.split(r"(\d+)", str(path).lower()):
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def discover_sources(game_root: Path) -> list[Path]:
    candidates: set[Path] = set()
    content = game_root / "content"
    dlc = game_root / "dlc"
    if content.is_dir():
        candidates.update(content.glob("content*/brpc.w3speech"))
    if dlc.is_dir():
        # A pasta DLC também pode conter mods instalados pelo usuário. Esses
        # pacotes não pertencem ao corpus original e podem usar outra versão
        # CPSW (por exemplo, v162). Consideramos somente os nomes oficiais.
        for child in dlc.iterdir():
            if child.is_dir() and OFFICIAL_DLC_RE.fullmatch(child.name):
                candidates.update(child.rglob("brpc.w3speech"))
    paths = sorted((path.resolve() for path in candidates if path.is_file()), key=natural_path_key)
    if not paths:
        raise FormatError(f"nenhum brpc.w3speech encontrado sob {game_root}")
    return paths


def prepare_selections(
    archives: Sequence[Archive], wem_paths: dict[int, Path]
) -> tuple[list[Selection], list[ReportRow], list[str]]:
    locations: dict[int, list[Location]] = {}
    targets = set(wem_paths)
    for source_index, archive in enumerate(archives):
        for entry_index, entry in enumerate(archive.entries):
            if entry.ident in targets:
                locations.setdefault(entry.ident, []).append(
                    Location(source_index, entry_index, archive, entry)
                )

    selections: list[Selection] = []
    rows: list[ReportRow] = []
    errors: list[str] = []
    for ident in sorted(targets):
        matches = locations.get(ident, [])
        if not matches:
            detail = "ID não encontrado nos pacotes descobertos"
            rows.append(ReportRow(ident, "ausente", detail=detail))
            errors.append(f"0x{ident:08x}: {detail}")
            continue
        try:
            replacement = wem_paths[ident]
            new_wem = parse_wem_bytes(replacement.read_bytes(), str(replacement))
            candidates = [read_original_candidate(item) for item in matches]
            duplicate_note = ""
            row_source = " | ".join(str(item.archive.path) for item in matches)
            chosen_candidates: list[OriginalCandidate]
            duplicate_status = "ok"
            if len(candidates) > 1:
                differences_list = candidate_differences(candidates)
                if not differences_list:
                    chosen_candidates = [candidates[-1]]
                    duplicate_status = "duplicado_equivalente"
                    duplicate_note = (
                        f"{len(candidates)} cópias equivalentes; selecionado "
                        f"{chosen_candidates[0].location.archive.path}"
                    )
                elif differences_list == ["id_high"]:
                    # O cabeçalho CPSW usa o par (id, id_high). O mesmo ID de
                    # mídia pode aparecer com mais de um componente alto. Como
                    # todos os demais bytes/metadados são idênticos, preservamos
                    # uma ocorrência de cada chave composta.
                    by_high: dict[int, OriginalCandidate] = {}
                    for candidate in candidates:
                        by_high[candidate.location.entry.ident_high] = candidate
                    chosen_candidates = [by_high[key] for key in sorted(by_high)]
                    duplicate_status = "id_high_expandido"
                    highs = ", ".join(
                        f"0x{item.location.entry.ident_high:08x}"
                        for item in chosen_candidates
                    )
                    duplicate_note = (
                        f"{len(chosen_candidates)} chaves compostas preservadas; "
                        f"id_high=[{highs}]"
                    )
                else:
                    differences = ", ".join(differences_list)
                    detail = (
                        f"cópias divergentes em [{differences}]; "
                        + " | ".join(candidate_summary(item) for item in candidates)
                    )
                    rows.append(
                        ReportRow(
                            ident,
                            "duplicado_divergente",
                            source=row_source,
                            new_codec=new_wem.family,
                            new_channels=str(new_wem.channels),
                            new_rate=str(new_wem.sample_rate),
                            new_duration=f"{new_wem.duration:.6f}",
                            detail=detail,
                        )
                    )
                    errors.append(f"0x{ident:08x}: {detail}")
                    continue
            else:
                chosen_candidates = [candidates[0]]

            representative = chosen_candidates[0]
            location = representative.location
            old_wem = representative.wem
            trailer_kind = representative.trailer_kind
            problems: list[str] = []
            if old_wem.family != new_wem.family:
                problems.append(f"codec {old_wem.family} -> {new_wem.family}")
            if old_wem.channels != new_wem.channels:
                problems.append(f"canais {old_wem.channels} -> {new_wem.channels}")
            if old_wem.sample_rate != new_wem.sample_rate:
                problems.append(
                    f"sample rate {old_wem.sample_rate} -> {new_wem.sample_rate}"
                )
            if new_wem.family != "wem-opus":
                problems.append(f"substituto não é WEM Opus: {new_wem.family}")
            report_selection = Selection(
                location, replacement, old_wem, new_wem, trailer_kind
            )
            status = (
                "incompatível"
                if problems
                else duplicate_status
            )
            detail = "; ".join(part for part in [duplicate_note, *problems] if part)
            rows.append(
                ReportRow(
                    ident=ident,
                    status=status,
                    source=row_source,
                    old_codec=old_wem.family,
                    new_codec=new_wem.family,
                    old_channels=str(old_wem.channels),
                    new_channels=str(new_wem.channels),
                    old_rate=str(old_wem.sample_rate),
                    new_rate=str(new_wem.sample_rate),
                    old_duration=f"{old_wem.duration:.6f}",
                    new_duration=f"{new_wem.duration:.6f}",
                    delta_pct=f"{report_selection.duration_delta_pct:+.3f}",
                    cr2w_size=str(location.entry.cr2w_size),
                    detail=detail,
                )
            )
            if problems:
                errors.append(f"0x{ident:08x}: {detail}")
            else:
                for chosen in chosen_candidates:
                    selections.append(
                        Selection(
                            chosen.location,
                            replacement,
                            chosen.wem,
                            new_wem,
                            chosen.trailer_kind,
                        )
                    )
        except (FormatError, OSError) as exc:
            rows.append(
                ReportRow(
                    ident,
                    "erro",
                    source=" | ".join(str(item.archive.path) for item in matches),
                    detail=str(exc),
                )
            )
            errors.append(f"0x{ident:08x}: {exc}")

    selections.sort(
        key=lambda item: (
            item.ident,
            item.location.entry.ident_high,
        )
    )
    return selections, rows, errors


def write_report(path: Path, rows: Sequence[ReportRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "id",
                "status",
                "pacote_original",
                "codec_original",
                "codec_novo",
                "canais_original",
                "canais_novo",
                "sample_rate_original",
                "sample_rate_novo",
                "duracao_original",
                "duracao_nova",
                "delta_pct",
                "cr2w_bytes",
                "detalhe",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    f"0x{row.ident:08x}",
                    row.status,
                    row.source,
                    row.old_codec,
                    row.new_codec,
                    row.old_channels,
                    row.new_channels,
                    row.old_rate,
                    row.new_rate,
                    row.old_duration,
                    row.new_duration,
                    row.delta_pct,
                    row.cr2w_size,
                    row.detail,
                ]
            )
    os.replace(partial, path)


def copy_range(source: BinaryIO, output: BinaryIO, offset: int, size: int) -> None:
    source.seek(offset)
    remaining = size
    while remaining:
        chunk = source.read(min(COPY_CHUNK, remaining))
        if not chunk:
            raise FormatError("fim inesperado durante cópia de CR2W")
        output.write(chunk)
        remaining -= len(chunk)


def calculate_compact_entries(
    selections: Sequence[Selection], key1: int, key2: int
) -> tuple[list[Entry], int]:
    count_bytes = encode_bit6(len(selections))
    header_size = 4 + 4 + 2 + len(count_bytes) + ENTRY_STRUCT.size * len(selections) + 2
    cursor = header_size
    entries: list[Entry] = []
    for selection in selections:
        old = selection.location.entry
        wave_size = selection.new_wem.size + 12
        cr2w_offset = cursor + wave_size if old.cr2w_size else 0
        new = Entry(
            ident=old.ident,
            ident_high=old.ident_high,
            wave_offset=cursor,
            zero1=0,
            wave_size=wave_size,
            zero2=0,
            cr2w_offset=cr2w_offset,
            zero3=0,
            cr2w_size=old.cr2w_size,
            zero4=0,
        )
        entries.append(new)
        cursor += wave_size + old.cr2w_size
        if cursor > 0xFFFFFFFF:
            raise FormatError(
                "pacote compacto excederia 4 GiB, limite dos offsets uint32"
            )
    if key1 or key2:
        raise FormatError("chave de idioma inesperada")
    return entries, cursor


def build_compact(
    selections: Sequence[Selection], output_path: Path, *, force: bool
) -> None:
    if not selections:
        raise FormatError("nenhuma entrada compatível para gravar")
    source_paths = {item.location.archive.path.resolve() for item in selections}
    if output_path.resolve() in source_paths:
        raise FormatError("a saída não pode substituir um pacote original do jogo")
    if output_path.exists() and not force:
        raise FormatError(f"saída já existe: {output_path}; use --force conscientemente")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    if partial.exists():
        if not force:
            raise FormatError(f"arquivo parcial já existe: {partial}")
        partial.unlink()

    entries, expected_size = calculate_compact_entries(selections, 0, 0)
    try:
        with partial.open("xb") as output:
            output.write(MAGIC)
            output.write(U32.pack(SUPPORTED_VERSION))
            output.write(U16.pack(0))
            output.write(encode_bit6(len(entries)))
            for entry in entries:
                output.write(entry.pack())
            output.write(U16.pack(0))

            open_sources: dict[Path, BinaryIO] = {}
            try:
                for selection, entry in zip(selections, entries):
                    if output.tell() != entry.wave_offset:
                        raise FormatError(
                            f"offset inesperado em 0x{entry.ident:08x}: "
                            f"{output.tell()} vs {entry.wave_offset}"
                        )
                    output.write(U32.pack(selection.new_wem.size))
                    with selection.replacement.open("rb") as wem:
                        while True:
                            chunk = wem.read(COPY_CHUNK)
                            if not chunk:
                                break
                            output.write(chunk)
                    output.write(
                        WAVE_TRAILER.pack(
                            selection.new_wem.duration,
                            selection.trailer_kind,
                        )
                    )
                    if entry.cr2w_size:
                        source_path = selection.location.archive.path
                        source = open_sources.get(source_path)
                        if source is None:
                            source = source_path.open("rb")
                            open_sources[source_path] = source
                        copy_range(
                            source,
                            output,
                            selection.location.entry.cr2w_offset,
                            selection.location.entry.cr2w_size,
                        )
            finally:
                for source in open_sources.values():
                    source.close()

            output.flush()
            os.fsync(output.fileno())
            if output.tell() != expected_size:
                raise FormatError(
                    f"saída possui {output.tell()} bytes; esperado {expected_size}"
                )

        verify_compact(partial, selections)
        os.replace(partial, output_path)
    except Exception:
        print(f"Arquivo parcial preservado para diagnóstico: {partial}", file=sys.stderr)
        raise


def hash_range(handle: BinaryIO, offset: int, size: int) -> bytes:
    digest = hashlib.sha256()
    handle.seek(offset)
    remaining = size
    while remaining:
        chunk = read_exact(handle, min(COPY_CHUNK, remaining))
        digest.update(chunk)
        remaining -= len(chunk)
    return digest.digest()


def verify_compact(path: Path, selections: Sequence[Selection]) -> None:
    compact = parse_archive(path)
    if len(compact.entries) != len(selections):
        raise FormatError("verificação: quantidade de entradas divergente")
    with path.open("rb") as built:
        for entry, selection in zip(compact.entries, selections):
            if entry.ident != selection.ident:
                raise FormatError("verificação: ordem/ID divergente")
            built.seek(entry.wave_offset)
            wem_size = U32.unpack(read_exact(built, 4))[0]
            wem_data = read_exact(built, wem_size)
            duration, trailer_kind = WAVE_TRAILER.unpack(
                read_exact(built, WAVE_TRAILER.size)
            )
            if hashlib.sha256(wem_data).digest() != hashlib.sha256(
                selection.replacement.read_bytes()
            ).digest():
                raise FormatError(f"verificação: WEM divergente em 0x{entry.ident:08x}")
            if abs(duration - selection.new_wem.duration) > 0.001:
                raise FormatError(f"verificação: duração divergente em 0x{entry.ident:08x}")
            if trailer_kind != selection.trailer_kind:
                raise FormatError(f"verificação: trailer divergente em 0x{entry.ident:08x}")
            if entry.cr2w_size:
                with selection.location.archive.path.open("rb") as original:
                    if hash_range(built, entry.cr2w_offset, entry.cr2w_size) != hash_range(
                        original,
                        selection.location.entry.cr2w_offset,
                        selection.location.entry.cr2w_size,
                    ):
                        raise FormatError(
                            f"verificação: CR2W divergente em 0x{entry.ident:08x}"
                        )


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Localiza WEMs nos brpc.w3speech originais e monta um pacote "
            "compacto preservando os CR2W."
        )
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--wem-dir", type=Path, required=True)
    parser.add_argument(
        "--wem-override-dir",
        type=Path,
        action="append",
        default=[],
        help=(
            "pasta adicional cujos WEMs substituem os de --wem-dir; "
            "pode ser repetida"
        ),
    )
    parser.add_argument("--only-id", type=parse_id)
    parser.add_argument(
        "--skip-id",
        type=parse_id,
        action="append",
        default=[],
        help="omite explicitamente um ID inexistente; pode ser repetido",
    )
    parser.add_argument("--output", type=Path, help="brpc.w3speech compacto de saída")
    parser.add_argument("--report", type=Path, help="CSV de mapeamento")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        game_root = args.game_root.resolve()
        wem_dir = args.wem_dir.resolve()
        if not game_root.is_dir():
            raise FormatError(f"pasta do jogo não encontrada: {game_root}")
        if not wem_dir.is_dir():
            raise FormatError(f"pasta WEM não encontrada: {wem_dir}")

        wem_paths = scan_wems(wem_dir)
        for raw_override in args.wem_override_dir:
            override = raw_override.resolve()
            if not override.is_dir():
                raise FormatError(f"pasta WEM de sobreposição não encontrada: {override}")
            override_wems = scan_wems(override)
            wem_paths.update(override_wems)
            print(
                f"Sobreposição WEM: {override} ({len(override_wems)} arquivo(s))"
            )
        if args.only_id is not None:
            if args.only_id not in wem_paths:
                raise FormatError(
                    f"WEM 0x{args.only_id:08x} não encontrado em {wem_dir}"
                )
            wem_paths = {args.only_id: wem_paths[args.only_id]}
        skipped_rows: list[ReportRow] = []
        for ident in sorted(set(args.skip_id)):
            if args.only_id is not None and ident != args.only_id:
                continue
            if ident not in wem_paths:
                raise FormatError(
                    f"--skip-id 0x{ident:08x} não corresponde a um WEM selecionado"
                )
            del wem_paths[ident]
            skipped_rows.append(
                ReportRow(
                    ident,
                    "ignorado",
                    detail="omitido explicitamente por --skip-id",
                )
            )
        if not wem_paths:
            raise FormatError("nenhum WEM restou após aplicar --skip-id")
        print(f"WEMs selecionados: {len(wem_paths)}")
        if skipped_rows:
            print(f"WEMs omitidos explicitamente: {len(skipped_rows)}")

        source_paths = discover_sources(game_root)
        print(f"Pacotes brpc.w3speech descobertos: {len(source_paths)}")
        archives: list[Archive] = []
        for index, path in enumerate(source_paths, start=1):
            print(f"[{index}/{len(source_paths)}] Indexando {path}")
            archive = parse_archive(path, set(wem_paths))
            if archive.entries:
                archives.append(archive)
            else:
                print("  pacote vazio; ignorado")
        if not archives:
            raise FormatError("todos os pacotes descobertos estão vazios")

        selections, rows, errors = prepare_selections(archives, wem_paths)
        rows.extend(skipped_rows)
        rows.sort(key=lambda row: row.ident)
        report = (
            args.report.resolve()
            if args.report
            else wem_dir / "relatorio_mapeamento_w3speech.csv"
        )
        write_report(report, rows)

        missing = sum(row.status == "ausente" for row in rows)
        compatible_ids = sum(
            row.status in {"ok", "duplicado_equivalente", "id_high_expandido"}
            for row in rows
        )
        duplicates_ok = sum(row.status == "duplicado_equivalente" for row in rows)
        expanded_ids = sum(row.status == "id_high_expandido" for row in rows)
        duplicates_bad = sum(row.status == "duplicado_divergente" for row in rows)
        incompatible = sum(row.status in {"incompatível", "erro"} for row in rows)
        ignored = sum(row.status == "ignorado" for row in rows)
        print(
            f"Mapeamento: IDs_compatíveis={compatible_ids}, "
            f"entradas={len(selections)}, ausentes={missing}, "
            f"duplicados_resolvidos={duplicates_ok}, "
            f"IDs_high_expandidos={expanded_ids}, "
            f"duplicados_divergentes={duplicates_bad}, "
            f"incompatíveis={incompatible}, ignorados={ignored}"
        )
        print(f"Relatório: {report}")
        if selections:
            deltas = [selection.duration_delta_pct for selection in selections]
            estimated = (
                4
                + 4
                + 2
                + len(encode_bit6(len(selections)))
                + ENTRY_STRUCT.size * len(selections)
                + 2
                + sum(
                    selection.new_wem.size
                    + 12
                    + selection.location.entry.cr2w_size
                    for selection in selections
                )
            )
            print(
                f"Duração delta: [{min(deltas):+.1f}%, {max(deltas):+.1f}%]; "
                f"tamanho compacto estimado: {human_size(estimated)}"
            )
        if errors:
            preview = "\n  - ".join(errors[:20])
            suffix = "" if len(errors) <= 20 else f"\n  ... e mais {len(errors) - 20}"
            raise FormatError(f"mapeamento incompleto/incompatível:\n  - {preview}{suffix}")

        if args.output is None:
            print("Auditoria concluída; nenhum w3speech foi criado.")
            return 0

        output = args.output.resolve()
        print(f"Montando pacote compacto: {output}")
        build_compact(selections, output, force=args.force)
        print(f"OK: {output} ({human_size(output.stat().st_size)})")
        print("WEMs e CR2W validados byte a byte.")
        return 0
    except (FormatError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
