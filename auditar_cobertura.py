#!/usr/bin/env python3
"""Compara manifesto, WAVs, WEMs e relatório de mapeamento antes do build."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


HEX_FILE_RE = re.compile(r"^(0x[0-9a-fA-F]{8})\.(wav|wem)$", re.IGNORECASE)


class AuditError(RuntimeError):
    pass


def read_manifest(path: Path) -> tuple[set[str], set[str], list[list[str]]]:
    generate: set[str] = set()
    originals: set[str] = set()
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for line_number, row in enumerate(reader, start=2):
            ident = (row.get("id_hex") or "").strip().lower()
            action = (row.get("acao") or "").strip().lower()
            if not re.fullmatch(r"0x[0-9a-f]{8}", ident):
                raise AuditError(f"manifesto, linha {line_number}: ID inválido")
            if ident in generate or ident in originals:
                raise AuditError(f"manifesto contém ID duplicado: {ident}")
            if action == "gerar":
                generate.add(ident)
            elif action == "usar_original":
                originals.add(ident)
            else:
                raise AuditError(f"{ident}: ação inválida {action!r}")
            rows.append([ident, action, row.get("revisar") or ""])
    return generate, originals, rows


def scan(directory: Path, suffix: str) -> set[str]:
    result: set[str] = set()
    if not directory.is_dir():
        return result
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != suffix:
            continue
        match = HEX_FILE_RE.fullmatch(path.name)
        if match:
            result.add(match.group(1).lower())
    return result


def read_mapping(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            ident = (row.get("id") or row.get("id_hex") or "").strip().lower()
            if ident:
                result[ident] = (row.get("status") or "").strip().lower()
    return result


def read_processing(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for line_number, row in enumerate(reader, start=2):
            ident = (row.get("id_hex") or "").strip().lower()
            status = (row.get("status") or "").strip().lower()
            if not re.fullmatch(r"0x[0-9a-f]{8}", ident):
                raise AuditError(
                    f"relatório de pós-processamento, linha {line_number}: ID inválido"
                )
            if ident in result:
                raise AuditError(f"pós-processamento contém ID duplicado: {ident}")
            result[ident] = status
    if not result:
        raise AuditError(f"relatório de pós-processamento vazio: {path}")
    return result


def preview(values: set[str]) -> str:
    items = sorted(values)
    shown = ", ".join(items[:12])
    return shown + (f" e mais {len(items) - 12}" if len(items) > 12 else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--wav-dir", type=Path, required=True)
    parser.add_argument("--wem-dir", type=Path, required=True)
    parser.add_argument("--mapping-report", type=Path)
    parser.add_argument("--processing-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.processing_report and not args.processing_report.is_file():
            raise AuditError(
                f"relatório de pós-processamento não encontrado: {args.processing_report}"
            )
        generate, originals, manifest_rows = read_manifest(args.manifest)
        wavs = scan(args.wav_dir, ".wav")
        wems = scan(args.wem_dir, ".wem")
        mapping = read_mapping(args.mapping_report)
        processing = read_processing(args.processing_report)
        missing_wav = generate - wavs
        missing_wem = generate - wems
        extra_wav = wavs - generate
        extra_wem = wems - generate
        accepted_mapping = {
            "ok", "duplicado_equivalente", "id_high_expandido", "ignorado"
        }
        bad_mapping = {
            ident for ident in generate
            if mapping and mapping.get(ident, "ausente") not in accepted_mapping
        }
        accepted_processing = {"ok", "aviso_curta", "aviso_longa"}
        bad_processing = {
            ident for ident in generate
            if processing and processing.get(ident, "ausente") not in accepted_processing
        }
        review_ids = {ident for ident, _action, review in manifest_rows if review.strip()}

        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["categoria", "quantidade", "ids"])
            for name, values in [
                ("gerar", generate), ("usar_original", originals),
                ("revisao_pendente", review_ids), ("wav_faltando", missing_wav),
                ("wem_faltando", missing_wem), ("wav_extra", extra_wav),
                ("wem_extra", extra_wem),
                ("pos_processamento_invalido", bad_processing),
                ("mapeamento_invalido", bad_mapping),
            ]:
                writer.writerow([name, len(values), ",".join(sorted(values))])

        print(
            f"Corpus: gerar={len(generate)}, usar_original={len(originals)}, "
            f"revisar={len(review_ids)}"
        )
        print(f"Faltando: WAV={len(missing_wav)}, WEM={len(missing_wem)}")
        print(f"Extras: WAV={len(extra_wav)}, WEM={len(extra_wem)}")
        print(f"Mapeamento inválido/ausente: {len(bad_mapping)}")
        print(f"Pós-processamento inválido/ausente: {len(bad_processing)}")
        print(f"Relatório: {output}")
        failures = missing_wav | missing_wem | bad_mapping | bad_processing
        if failures:
            raise AuditError(f"cobertura incompleta: {preview(failures)}")
        if review_ids:
            raise AuditError(
                f"há {len(review_ids)} linha(s) sinalizada(s) para revisão manual"
            )
        print("Cobertura aprovada.")
        return 0
    except (AuditError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
