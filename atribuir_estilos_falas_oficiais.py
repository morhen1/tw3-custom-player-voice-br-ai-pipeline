#!/usr/bin/env python3
"""Agrupa perfis de falas oficiais em referências expressivas auditáveis."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


class StyleAssignmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class StyleDefinition:
    reference_id: str
    description: str
    semantic_triggers: str
    expected_delivery: str
    direct_match: bool = False


STYLES = (
    StyleDefinition(
        "alerta_tenso",
        "Reação curta de surpresa, perigo ou hesitação.",
        "exclamação; pergunta muito curta; pergunta curta com reticências",
        "curta, ataque rápido, tensão audível",
        True,
    ),
    StyleDefinition(
        "investigacao_observacional",
        "Leitura de pistas e deduções ditas enquanto a personagem examina o ambiente.",
        "pegadas, monstro, anotações, caminho bloqueado, rastros, cavernas, assassinato",
        "contida, pausas funcionais, tom atento",
    ),
    StyleDefinition(
        "pergunta_cautelosa",
        "Pergunta conversacional sem urgência ou confronto.",
        "interrogação sem gatilho de alerta, pista ou ironia",
        "natural, curiosa, intensidade baixa ou média",
    ),
    StyleDefinition(
        "confronto_firme",
        "Cobrança ou acusação direta, com controle e autoridade.",
        "acordo, acusação, contestação direta, Nilfgaard",
        "firme, articulada, energia alta sem grito",
        True,
    ),
    StyleDefinition(
        "ironia_seca",
        "Humor discreto, provocação ou autocorreção irônica.",
        "astúcia/digno; insinuação; autocorreção com reticências",
        "seca, leve sorriso vocal, pausas deliberadas",
    ),
    StyleDefinition(
        "narrativa_contida",
        "Explicação ou raciocínio longo que precisa manter fluidez.",
        "fala com pelo menos 25 palavras ou duração oficial de pelo menos 8 segundos",
        "cadência estável, pausas sintáticas, sem pressa",
    ),
    StyleDefinition(
        "conversa_neutra",
        "Fala cotidiana ou declaração sem emoção dominante.",
        "regra de fallback sem gatilho mais específico",
        "natural, direta, intensidade moderada",
    ),
)

STYLE_BY_ID = {style.reference_id: style for style in STYLES}
REFERENCE_AUDIO = "private/referencias/referencia_base.wav"
REFERENCE_TEXT = "private/referencias/referencia_base.txt"
REFERENCE_PROMPT = "private/referencias/referencia_base.pt"

IRONY_FRAGMENTS = (
    "astucia",
    "digno de um cavaleiro",
    "interacao mais intima",
    "bruxos digo nos",
)
CONFRONTATION_FRAGMENTS = ("acordo com", "nilfgaard")
INVESTIGATION_FRAGMENTS = (
    "pegada",
    "monstro",
    "anotac",
    "trancad",
    "outro caminho",
    "fezes de insetos",
    "caverna",
    "assassinato",
    "teoria",
    "raciocinio",
)


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()


def parse_float(value: str, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise StyleAssignmentError(f"valor inválido em {field}: {value!r}") from exc


def assign_style(row: dict[str, str]) -> tuple[str, str, str]:
    text = (row.get("texto_atual") or "").strip()
    normalized = normalize_text(text)
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    duration = parse_float(row.get("duracao_audio_s") or "", "duracao_audio_s")
    markers = set(filter(None, (row.get("marcadores_texto") or "").split("|")))
    acoustic = (
        f"{row.get('classe_ritmo', '')}/"
        f"{row.get('classe_intensidade', '')}/"
        f"{row.get('classe_pausas', '')}"
    )

    if any(fragment in normalized for fragment in IRONY_FRAGMENTS):
        return "ironia_seca", "alta", f"gatilho semântico de ironia; acústica={acoustic}"
    if any(fragment in normalized for fragment in CONFRONTATION_FRAGMENTS):
        return "confronto_firme", "alta", f"cobrança/confronto explícito; acústica={acoustic}"
    if len(words) >= 25 or duration >= 8.0:
        return "narrativa_contida", "alta", f"fala longa ({len(words)} palavras, {duration:.2f}s); acústica={acoustic}"
    if any(fragment in normalized for fragment in INVESTIGATION_FRAGMENTS):
        return "investigacao_observacional", "alta", f"vocabulário de pista/dedução; acústica={acoustic}"
    if (
        "exclamacao" in markers
        or ("pergunta" in markers and len(words) <= 3)
        or ("pergunta" in markers and "reticencias" in markers and len(words) <= 6)
    ):
        return "alerta_tenso", "media", f"reação curta ou hesitante; acústica={acoustic}"
    if "pergunta" in markers:
        return "pergunta_cautelosa", "media", f"pergunta sem urgência explícita; acústica={acoustic}"
    return "conversa_neutra", "media", f"nenhum gatilho mais específico; acústica={acoustic}"


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise StyleAssignmentError(f"CSV não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {
            "id_hex",
            "texto_atual",
            "duracao_audio_s",
            "classe_ritmo",
            "classe_intensidade",
            "classe_pausas",
            "marcadores_texto",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise StyleAssignmentError("colunas ausentes: " + ", ".join(missing))
        rows = list(reader)
        if not rows:
            raise StyleAssignmentError("CSV vazio")
        return list(reader.fieldnames), rows


def write_enriched(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    added = [
        "estilo_id",
        "estilo_descricao",
        "confianca_estilo",
        "criterios_estilo",
        "ref_audio_atual",
        "ref_text_file_atual",
        "prompt_atual",
        "status_referencia",
        "preprocess_prompt",
    ]
    output_fields = list(fieldnames)
    for field in added:
        if field not in output_fields:
            output_fields.append(field)
    if "reference_id" not in output_fields:
        output_fields.append("reference_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_assignments(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["id_hex", "estilo"])
        writer.writerows((row["id_hex"], row["estilo_id"]) for row in rows)


def write_catalog(path: Path, counts: Counter[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(
            [
                "reference_id",
                "descricao",
                "gatilhos_semanticos",
                "entrega_esperada",
                "falas_piloto",
                "ref_audio_atual",
                "ref_text_file_atual",
                "prompt_atual",
                "status_atual",
                "preprocess_prompt",
            ]
        )
        for style in STYLES:
            writer.writerow(
                [
                    style.reference_id,
                    style.description,
                    style.semantic_triggers,
                    style.expected_delivery,
                    counts[style.reference_id],
                    REFERENCE_AUDIO,
                    REFERENCE_TEXT,
                    REFERENCE_PROMPT,
                    "correspondencia_direta" if style.direct_match else "fallback_pandora",
                    "true",
                ]
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assignments-output", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        fieldnames, rows = read_rows(args.input)
        counts: Counter[str] = Counter()
        seen_ids: set[str] = set()
        for row in rows:
            ident = (row.get("id_hex") or "").strip().lower()
            if not re.fullmatch(r"0x[0-9a-f]{8}", ident):
                raise StyleAssignmentError(f"ID inválido: {ident}")
            if ident in seen_ids:
                raise StyleAssignmentError(f"ID repetido: {ident}")
            seen_ids.add(ident)
            style_id, confidence, criteria = assign_style(row)
            style = STYLE_BY_ID[style_id]
            row["id_hex"] = ident
            row["estilo_id"] = style_id
            row["estilo_descricao"] = style.description
            row["confianca_estilo"] = confidence
            row["criterios_estilo"] = criteria
            row["reference_id"] = style_id
            row["ref_audio_atual"] = REFERENCE_AUDIO
            row["ref_text_file_atual"] = REFERENCE_TEXT
            row["prompt_atual"] = REFERENCE_PROMPT
            row["status_referencia"] = (
                "correspondencia_direta" if style.direct_match else "fallback_pandora"
            )
            row["preprocess_prompt"] = "true"
            counts[style_id] += 1
        write_enriched(args.output, fieldnames, rows)
        write_assignments(args.assignments_output, rows)
        write_catalog(args.catalog_output, counts)
        print(f"Falas classificadas: {len(rows)}")
        print("Estilos: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
        print(f"CSV enriquecido: {args.output}")
        print(f"Atribuições: {args.assignments_output}")
        print(f"Catálogo: {args.catalog_output}")
        return 0
    except (StyleAssignmentError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
