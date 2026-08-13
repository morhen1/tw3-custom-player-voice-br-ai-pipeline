#!/usr/bin/env python3
"""Extrai WEMs oficiais de arquivos brpc.w3speech por ID.

O script reutiliza o parser estrutural do montador compacto, resolve apenas
duplicatas equivalentes e nunca modifica os pacotes do jogo.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from montar_brpc_w3speech_compacto_v4 import (
    FormatError,
    Location,
    U32,
    candidate_differences,
    discover_sources,
    parse_archive,
    parse_wem_bytes,
    read_exact,
    read_original_candidate,
)


@dataclass(frozen=True)
class ExtractionRow:
    ident: int
    status: str
    source: str = ""
    ident_high: str = ""
    codec: str = ""
    channels: str = ""
    sample_rate: str = ""
    duration: str = ""
    wem_bytes: str = ""
    occurrences: str = ""
    detail: str = ""


def parse_ident(value: object, label: str) -> int:
    if isinstance(value, int):
        ident = value
    elif isinstance(value, str):
        try:
            ident = int(value.strip(), 0)
        except ValueError as exc:
            raise FormatError(f"{label}: ID inválido {value!r}") from exc
    else:
        raise FormatError(f"{label}: ID ausente ou inválido")
    if not 0 <= ident <= 0xFFFFFFFF:
        raise FormatError(f"{label}: ID fora de uint32")
    return ident


def load_jsonl_ids(path: Path) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise FormatError(f"{path}, linha {line_number}: JSON inválido") from exc
        ident = parse_ident(record.get("id"), f"{path}, linha {line_number}")
        if ident in seen:
            raise FormatError(f"{path}, linha {line_number}: ID repetido 0x{ident:08x}")
        seen.add(ident)
        ids.append(ident)
    if not ids:
        raise FormatError(f"nenhum ID encontrado em {path}")
    return ids


def load_text_ids(path: Path) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        token = raw_line.split("#", 1)[0].strip()
        if not token:
            continue
        ident = parse_ident(token, f"{path}, linha {line_number}")
        if ident in seen:
            raise FormatError(f"{path}, linha {line_number}: ID repetido 0x{ident:08x}")
        seen.add(ident)
        ids.append(ident)
    if not ids:
        raise FormatError(f"nenhum ID encontrado em {path}")
    return ids


def read_wem(location: Location) -> bytes:
    entry = location.entry
    with location.archive.path.open("rb") as handle:
        handle.seek(entry.wave_offset)
        size = U32.unpack(read_exact(handle, U32.size))[0]
        if size + 12 != entry.wave_size:
            raise FormatError(
                f"{location.archive.path}: tamanho WEM divergente em "
                f"0x{entry.ident:08x}"
            )
        return read_exact(handle, size)


def write_report(path: Path, rows: Sequence[ExtractionRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "id_hex",
                "status",
                "pacote_original",
                "id_high",
                "codec",
                "canais",
                "sample_rate",
                "duracao_s",
                "wem_bytes",
                "ocorrencias",
                "detalhe",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    f"0x{row.ident:08x}",
                    row.status,
                    row.source,
                    row.ident_high,
                    row.codec,
                    row.channels,
                    row.sample_rate,
                    row.duration,
                    row.wem_bytes,
                    row.occurrences,
                    row.detail,
                ]
            )
    os.replace(partial, path)


def extract_official_wems(
    game_root: Path,
    ids: Sequence[int],
    output_dir: Path,
    report_path: Path,
    *,
    force: bool = False,
) -> tuple[list[ExtractionRow], list[str]]:
    targets = set(ids)
    if len(targets) != len(ids):
        raise FormatError("a seleção contém IDs repetidos")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_paths = discover_sources(game_root)
    print(f"Pacotes brpc.w3speech descobertos: {len(source_paths)}")
    archives = []
    for index, source in enumerate(source_paths, start=1):
        print(f"[{index}/{len(source_paths)}] Indexando {source}")
        archive = parse_archive(source, targets)
        if archive.entries:
            archives.append(archive)

    locations: dict[int, list[Location]] = {}
    for source_index, archive in enumerate(archives):
        for entry_index, entry in enumerate(archive.entries):
            if entry.ident in targets:
                locations.setdefault(entry.ident, []).append(
                    Location(source_index, entry_index, archive, entry)
                )

    rows: list[ExtractionRow] = []
    errors: list[str] = []
    for progress, ident in enumerate(ids, start=1):
        matches = locations.get(ident, [])
        if not matches:
            detail = "ID não encontrado nos pacotes oficiais"
            rows.append(ExtractionRow(ident, "ausente", detail=detail))
            errors.append(f"0x{ident:08x}: {detail}")
            continue
        try:
            candidates = [read_original_candidate(location) for location in matches]
            differences = candidate_differences(candidates)
            if differences and differences != ["id_high"]:
                detail = "duplicatas divergentes em: " + ", ".join(differences)
                rows.append(
                    ExtractionRow(
                        ident,
                        "duplicado_divergente",
                        source=" | ".join(str(item.archive.path) for item in matches),
                        occurrences=str(len(matches)),
                        detail=detail,
                    )
                )
                errors.append(f"0x{ident:08x}: {detail}")
                continue

            chosen = candidates[-1]
            location = chosen.location
            wem_data = read_wem(location)
            info = parse_wem_bytes(wem_data, f"0x{ident:08x}")
            destination = output_dir / f"0x{ident:08x}.wem"
            if destination.exists() and not force:
                raise FormatError(f"saída já existe: {destination}")
            partial = destination.with_suffix(destination.suffix + ".partial")
            partial.write_bytes(wem_data)
            os.replace(partial, destination)
            status = "duplicado_resolvido" if len(matches) > 1 else "ok"
            detail = ""
            if len(matches) > 1:
                detail = (
                    f"{len(matches)} ocorrências equivalentes; selecionada a última "
                    "na ordem oficial"
                )
            rows.append(
                ExtractionRow(
                    ident=ident,
                    status=status,
                    source=str(location.archive.path),
                    ident_high=f"0x{location.entry.ident_high:08x}",
                    codec=info.family,
                    channels=str(info.channels),
                    sample_rate=str(info.sample_rate),
                    duration=f"{info.duration:.6f}",
                    wem_bytes=str(len(wem_data)),
                    occurrences=str(len(matches)),
                    detail=detail,
                )
            )
            if progress == 1 or progress == len(ids) or progress % 25 == 0:
                print(f"Progresso: {progress}/{len(ids)}")
        except (FormatError, OSError) as exc:
            rows.append(
                ExtractionRow(
                    ident,
                    "erro",
                    source=" | ".join(str(item.archive.path) for item in matches),
                    occurrences=str(len(matches)),
                    detail=str(exc),
                )
            )
            errors.append(f"0x{ident:08x}: {exc}")

    write_report(report_path, rows)
    return rows, errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrai WEMs oficiais de brpc.w3speech por ID sem alterar o jogo."
    )
    parser.add_argument("--game-root", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--selection-jsonl", type=Path)
    selection.add_argument("--ids-file", type=Path)
    selection.add_argument("--only-id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        game_root = args.game_root.resolve()
        output_dir = args.output.resolve()
        report_path = args.report.resolve()
        if not game_root.is_dir():
            raise FormatError(f"pasta do jogo não encontrada: {game_root}")
        if args.selection_jsonl:
            ids = load_jsonl_ids(args.selection_jsonl.resolve())
        elif args.ids_file:
            ids = load_text_ids(args.ids_file.resolve())
        else:
            ids = [parse_ident(args.only_id, "--only-id")]
        print(f"IDs selecionados: {len(ids)}")
        rows, errors = extract_official_wems(
            game_root,
            ids,
            output_dir,
            report_path,
            force=args.force,
        )
        extracted = sum(row.status in {"ok", "duplicado_resolvido"} for row in rows)
        print(f"Extraídos: {extracted}/{len(ids)}")
        print(f"Relatório: {report_path}")
        if errors:
            print(f"ERRO: {len(errors)} item(ns) não foram extraídos", file=sys.stderr)
            return 1
        print("Extração concluída e validada.")
        return 0
    except (FormatError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
