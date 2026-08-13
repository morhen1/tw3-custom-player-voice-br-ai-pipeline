#!/usr/bin/env python3
"""Aplica referências de voz por estilo a um JSONL já preparado."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


class MultiReferenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceReference:
    name: str
    enabled: bool
    ref_audio: Path | None
    ref_text_file: Path | None
    prompt: Path | None
    preprocess_prompt: bool


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if len(token) != 10 or not token.startswith("0x"):
        raise MultiReferenceError(f"ID inválido: {value}")
    try:
        int(token[2:], 16)
    except ValueError as exc:
        raise MultiReferenceError(f"ID inválido: {value}") from exc
    return token


def optional_path(base: Path, value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> tuple[str, dict[str, VoiceReference]]:
    if not path.is_file():
        raise MultiReferenceError(f"configuração não encontrada: {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    default_style = str(data.get("estilos", {}).get("padrao", "")).strip()
    if not default_style:
        raise MultiReferenceError("[estilos].padrao não foi definido")
    raw_references = data.get("referencias", {})
    if not isinstance(raw_references, dict) or not raw_references:
        raise MultiReferenceError("nenhuma [referencias.*] foi definida")
    references: dict[str, VoiceReference] = {}
    for name, raw in raw_references.items():
        if not isinstance(raw, dict):
            raise MultiReferenceError(f"referência inválida: {name}")
        reference = VoiceReference(
            name=name,
            enabled=bool(raw.get("enabled", False)),
            ref_audio=optional_path(path.parent, raw.get("ref_audio")),
            ref_text_file=optional_path(path.parent, raw.get("ref_text_file")),
            prompt=optional_path(path.parent, raw.get("prompt")),
            preprocess_prompt=bool(raw.get("preprocess_prompt", True)),
        )
        if reference.enabled:
            if reference.ref_audio is None or not reference.ref_audio.is_file():
                raise MultiReferenceError(
                    f"{name}: ref_audio ausente: {reference.ref_audio}"
                )
            if reference.ref_text_file is None or not reference.ref_text_file.is_file():
                raise MultiReferenceError(
                    f"{name}: ref_text_file ausente: {reference.ref_text_file}"
                )
            if reference.prompt is not None and not reference.prompt.is_file():
                raise MultiReferenceError(f"{name}: prompt ausente: {reference.prompt}")
        references[name] = reference
    if default_style not in references or not references[default_style].enabled:
        raise MultiReferenceError(f"estilo padrão não está habilitado: {default_style}")
    return default_style, references


def read_assignments(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise MultiReferenceError(f"atribuições não encontradas: {path}")
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "estilo"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise MultiReferenceError("CSV deve conter id_hex;estilo")
        for line_number, row in enumerate(reader, start=2):
            ident = normalize_id(row.get("id_hex") or "")
            style = (row.get("estilo") or "").strip()
            if not style:
                raise MultiReferenceError(f"linha {line_number}: estilo vazio")
            if ident in result:
                raise MultiReferenceError(f"ID repetido nas atribuições: {ident}")
            result[ident] = style
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--default-style")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.jsonl.is_file():
            raise MultiReferenceError(f"JSONL não encontrado: {args.jsonl}")
        configured_default, references = load_config(args.config)
        default_style = args.default_style or configured_default
        if default_style not in references or not references[default_style].enabled:
            raise MultiReferenceError(f"estilo padrão não habilitado: {default_style}")
        assignments = read_assignments(args.assignments)
        output_rows: list[dict[str, object]] = []
        report_rows: list[list[str]] = []
        seen_ids: set[str] = set()
        text_cache: dict[Path, str] = {}
        with args.jsonl.open("r", encoding="utf-8-sig") as handle:
            for line_number, raw in enumerate(handle, start=1):
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise MultiReferenceError(
                        f"JSON inválido em {args.jsonl}, linha {line_number}"
                    ) from exc
                ident = normalize_id(str(payload.get("id", "")))
                if ident in seen_ids:
                    raise MultiReferenceError(f"ID repetido no JSONL: {ident}")
                seen_ids.add(ident)
                style = assignments.get(ident, default_style)
                reference = references.get(style)
                if reference is None or not reference.enabled:
                    raise MultiReferenceError(
                        f"{ident}: estilo ausente ou desabilitado: {style}"
                    )
                assert reference.ref_audio is not None
                assert reference.ref_text_file is not None
                if reference.ref_text_file not in text_cache:
                    ref_text = reference.ref_text_file.read_text(
                        encoding="utf-8-sig"
                    ).strip()
                    if not ref_text:
                        raise MultiReferenceError(f"texto vazio: {reference.ref_text_file}")
                    text_cache[reference.ref_text_file] = ref_text
                payload["ref_audio"] = str(reference.ref_audio.resolve())
                payload["ref_text"] = text_cache[reference.ref_text_file]
                output_rows.append(payload)
                report_rows.append(
                    [
                        ident,
                        style,
                        str(reference.ref_audio.resolve()),
                        str(reference.prompt.resolve()) if reference.prompt else "",
                        str(reference.preprocess_prompt).lower(),
                    ]
                )
        unknown_assignments = sorted(set(assignments) - seen_ids)
        if unknown_assignments:
            raise MultiReferenceError(
                "atribuições para IDs ausentes: " + ", ".join(unknown_assignments[:10])
            )
        if not output_rows:
            raise MultiReferenceError("JSONL de entrada vazio")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            for payload in output_rows:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                ["id_hex", "estilo", "ref_audio", "prompt", "preprocess_prompt"]
            )
            writer.writerows(report_rows)
        counts: dict[str, int] = {}
        for row in report_rows:
            counts[row[1]] = counts.get(row[1], 0) + 1
        print(f"Falas: {len(output_rows)}")
        print("Estilos: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
        print(f"JSONL: {args.output}")
        print(f"Relatório: {args.report}")
        return 0
    except (MultiReferenceError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
