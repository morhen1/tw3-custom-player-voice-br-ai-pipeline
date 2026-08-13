#!/usr/bin/env python3
"""Seleciona uma amostra estratificada por duração de um JSONL do OmniVoice."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path


class SampleError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    ident: str
    duration: float
    payload: dict[str, object]


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if len(token) != 10 or not token.startswith("0x"):
        raise SampleError(f"ID inválido: {value}")
    try:
        int(token[2:], 16)
    except ValueError as exc:
        raise SampleError(f"ID inválido: {value}") from exc
    return token


def read_manifest(path: Path) -> dict[str, tuple[float, str]]:
    result: dict[str, tuple[float, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "duracao_original"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise SampleError(
                f"{path}: manifesto deve conter id_hex;acao;duracao_original"
            )
        for line_number, row in enumerate(reader, start=2):
            if (row.get("acao") or "").strip().lower() != "gerar":
                continue
            try:
                ident = normalize_id(row.get("id_hex") or "")
                duration = float((row.get("duracao_original") or "").replace(",", "."))
            except ValueError as exc:
                raise SampleError(
                    f"{path}, linha {line_number}: duração inválida"
                ) from exc
            if duration <= 0:
                raise SampleError(f"{path}, linha {line_number}: duração deve ser positiva")
            text = (row.get("texto_final") or row.get("texto_original") or "").strip()
            result[ident] = (duration, text)
    if not result:
        raise SampleError(f"nenhuma fala gerável com duração em {path}")
    return result


def read_jsonl(path: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SampleError(f"{path}, linha {line_number}: JSON inválido") from exc
            ident = normalize_id(str(payload.get("id", "")))
            if ident in result:
                raise SampleError(f"ID repetido no JSONL: {ident}")
            payload["id"] = ident
            # A amostra nunca deve reintroduzir o corte por duração.
            payload.pop("duration", None)
            result[ident] = payload
    if not result:
        raise SampleError(f"JSONL vazio: {path}")
    return result


def stratified_candidates(
    payloads: dict[str, dict[str, object]],
    manifest: dict[str, tuple[float, str]],
) -> list[Candidate]:
    candidates = [
        Candidate(ident, manifest[ident][0], payload)
        for ident, payload in payloads.items()
        if ident in manifest
    ]
    if not candidates:
        raise SampleError("JSONL e manifesto não possuem IDs geráveis em comum")
    return sorted(candidates, key=lambda item: (item.duration, item.ident))


def choose_evenly(
    candidates: list[Candidate], count: int, include_ids: list[str]
) -> list[Candidate]:
    if count < 1:
        raise SampleError("--count deve ser positivo")
    by_id = {item.ident: item for item in candidates}
    chosen: dict[str, Candidate] = {}
    for ident in include_ids:
        if ident not in by_id:
            raise SampleError(f"ID obrigatório ausente da seleção: {ident}")
        chosen[ident] = by_id[ident]
    if len(chosen) > count:
        raise SampleError("há mais --include-id do que o tamanho da amostra")

    target_count = min(count, len(candidates))
    slots = target_count - len(chosen)
    if slots == 1:
        indexes = [len(candidates) // 2]
    elif slots <= 0:
        indexes = []
    else:
        indexes = [round(i * (len(candidates) - 1) / (slots - 1)) for i in range(slots)]
    for index in indexes:
        if len(chosen) >= target_count:
            break
        chosen.setdefault(candidates[index].ident, candidates[index])

    # Arredondamentos e IDs obrigatórios podem reduzir a quantidade; complete
    # usando candidatos ainda não escolhidos, mantendo a ordem de duração.
    for candidate in candidates:
        if len(chosen) >= target_count:
            break
        chosen.setdefault(candidate.ident, candidate)
    return sorted(chosen.values(), key=lambda item: (item.duration, item.ident))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--include-id", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.jsonl.is_file():
            raise SampleError(f"JSONL não encontrado: {args.jsonl}")
        if not args.manifest.is_file():
            raise SampleError(f"manifesto não encontrado: {args.manifest}")
        include_ids = [normalize_id(value) for value in args.include_id]
        manifest = read_manifest(args.manifest)
        payloads = read_jsonl(args.jsonl)
        candidates = stratified_candidates(payloads, manifest)
        selected = choose_evenly(candidates, args.count, include_ids)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            for item in selected:
                handle.write(json.dumps(item.payload, ensure_ascii=False) + "\n")
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "duracao_original", "texto"])
            for item in selected:
                writer.writerow([
                    item.ident,
                    f"{item.duration:.6f}",
                    manifest[item.ident][1],
                ])
        durations = [item.duration for item in selected]
        print(
            f"Amostra: {len(selected)} fala(s); duração original "
            f"[{min(durations):.3f}s, {max(durations):.3f}s]"
        )
        print(f"JSONL: {args.output}")
        print(f"Relatório: {args.report}")
        return 0
    except (SampleError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
