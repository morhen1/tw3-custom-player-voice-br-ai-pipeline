#!/usr/bin/env python3
"""Audita concordância feminina e resíduos de ações/vocalizações no texto efetivo."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path


class PortugueseAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    ident: str
    category: str
    confidence: str
    current_text: str
    proposed_text: str
    proposed_action: str
    detail: str


ACTION_TERMS = {
    "suspiro", "suspira", "suspirar", "sniff", "snif", "cheira", "cheirando",
    "cof", "cof cof", "assobio", "assobia", "zomba", "risos", "riso", "tsc",
    "hrrm", "grunhe", "grunhido", "geme", "gemido", "ofega", "ofegante",
    "respira fundo", "boceja", "engasga", "arrota", "fungada", "funga",
}

GENDER_PAIRS = {
    "pronto": "pronta", "intrigado": "intrigada", "sozinho": "sozinha",
    "surpreso": "surpresa", "preocupado": "preocupada", "cansado": "cansada",
    "ocupado": "ocupada", "interessado": "interessada", "disposto": "disposta",
    "curioso": "curiosa", "velho": "velha", "confuso": "confusa",
    "enganado": "enganada", "furioso": "furiosa", "nomeado": "nomeada",
    "morto": "morta", "esquartejado": "esquartejada", "vivo": "viva",
    "satisfeito": "satisfeita", "preparado": "preparada", "nervoso": "nervosa",
    "sóbrio": "sóbria", "chocado": "chocada", "derrotado": "derrotada",
    "vestido": "vestida", "sujeito": "sujeita", "tolo": "tola",
    "criterioso": "criteriosa", "astuto": "astuta", "ansioso": "ansiosa",
    "discreto": "discreta", "classificado": "classificada", "preso": "presa",
    "forasteiro": "forasteira", "andarilho": "andarilha", "jogado": "jogada",
    "puxado": "puxada", "fascinado": "fascinada", "levado": "levada",
    "convidado": "convidada", "inteiro": "inteira", "chegado": "chegada",
    "acostumado": "acostumada", "caçado": "caçada", "atrasado": "atrasada",
    "aliviado": "aliviada", "perdido": "perdida", "convencido": "convencida",
    "certo": "certa", "errado": "errada", "fraco": "fraca", "culpado": "culpada",
    "conhecido": "conhecida", "cego": "cega", "novo": "nova", "bom": "boa",
    "ganancioso": "gananciosa", "inimigo": "inimiga", "bárbaro": "bárbara",
    "aluno": "aluna", "digno": "digna", "bandido": "bandida",
    "assassino": "assassina", "amigo": "amiga", "criado": "criada",
    "sortudo": "sortuda", "habilidoso": "habilidosa", "armado": "armada",
    "bruxo": "bruxa", "homem": "mulher", "garoto": "garota", "rapaz": "moça",
    "cavalheiro": "dama", "herói": "heroína", "ladrão": "ladra",
    "matador": "matadora", "prisioneiro": "prisioneira", "soldado": "soldada",
    "instrutor": "instrutora", "carrasco": "carrasca", "viajante": "viajante",
    "profissional": "profissional", "especialista": "especialista",
}

STAR_RE = re.compile(r"(?:\{\s*)?\*([^*]{1,80})\*(?:\s*\})?", re.IGNORECASE)
VOCAL_PATTERN = (
    r"(?<![\w-])(?:a{2,12}-?argh|a{1,12}rgh|argh|urgh|ugh|agh|ahg|"
    r"cof|tsc|ffwsshht)(?![\w-])"
)
VOCAL_RE = re.compile(VOCAL_PATTERN, re.IGNORECASE)
VOCAL_WITH_PUNCT_RE = re.compile(
    VOCAL_PATTERN + r"(?:\s*[,.;:!?…]+)?",
    re.IGNORECASE,
)
FIRST_PERSON_RE = re.compile(
    r"\b(?P<prefix>eu\s+sou|sou|estou|fiquei|continuo|pareço|me\s+sinto|"
    r"fui|serei|eu\s+estava|ando|(?:creio|acho|penso)\s+que\s+estava)\s+"
    r"(?P<article>um|o|esse|aquele)?\s*"
    r"(?P<word>[A-Za-zÀ-ÖØ-öø-ÿ]+)\b",
    re.IGNORECASE,
)
SAME_RE = re.compile(r"\b(?P<subject>eu|mim)\s+mesmo\b", re.IGNORECASE)


# Resíduos confirmados manualmente depois de uma busca morfológica mais ampla.
# A edição continua vinculada ao ID para não feminizar adjetivos referentes a
# NPCs, monstros, objetos, títulos citados ou charadas.
MANUAL_GENDER_EDITS: dict[str, list[tuple[str, str]]] = {
    "0x0005d68f": [("impressionado", "impressionada")],
    "0x0006213b": [("atacado", "atacada")],
    "0x00062dbd": [("entediado", "entediada")],
    "0x00062ec0": [("atacado", "atacada")],
    "0x00069f9d": [("ser pago", "ser paga")],
    "0x0006eb41": [("ensinado", "ensinada")],
    "0x0006f88a": [
        ("Serei o Grão-mestre", "Serei a Grã-mestra"),
        ("a Sumo Sacerdotisa", "a Suma Sacerdotisa"),
    ],
    "0x00076c93": [("Serei pago", "Serei paga")],
    "0x0007d09c": [("montado", "montada")],
    "0x0007f3c9": [("nocauteado", "nocauteada")],
    "0x000819fa": [("ousado", "ousada")],
    "0x00081a35": [("ser pago", "ser paga")],
    "0x00081b65": [("quentinho", "quentinha")],
    "0x00082f4e": [("teletransportado", "teletransportada")],
    "0x00083559": [("andar armado", "andar armada")],
    "0x00083768": [("contemplativo", "contemplativa")],
    "0x00089119": [("ficar atento", "ficar atenta")],
    "0x000898ad": [("convocado", "convocada")],
    "0x0008b12c": [("estou limpo", "estou limpa")],
    "0x0008b861": [("ficar bêbado", "ficar bêbada")],
    "0x0008e100": [("interrompido", "interrompida")],
    "0x0008e148": [("grato", "grata")],
    "0x0008fe74": [("ficar bêbado", "ficar bêbada")],
    "0x0008fe7c": [("impressionado", "impressionada")],
    "0x000fe533": [("ficar quieto", "ficar quieta")],
    "0x0010340b": [("teletransportado", "teletransportada")],
    "0x001065bc": [("empolgado", "empolgada")],
    "0x001069fe": [("desacordado", "desacordada")],
    "0x0010bff9": [("virado marujo", "virado marinheira")],
    "0x0010debb": [("grato", "grata")],
    "0x00110e9f": [("Honrado", "Honrada")],
    "0x00119008": [("impressionado", "impressionada")],
    "0x00119525": [("de cavaleiro para cavaleiro", "de cavaleira para cavaleiro")],
    "0x00119967": [("um garotinho", "uma garotinha")],
    "0x0011c238": [("honrado", "honrada")],
    "0x0011ea0a": [("convocado", "convocada")],
    "0x00121e9a": [("ficar atento", "ficar atenta")],
    "0x00121fa3": [("honrado", "honrada")],
    "0x001249a6": [("grato", "grata")],
    "0x001253fc": [("honrado", "honrada")],
    "0x001265d9": [("ficar bem atento", "ficar bem atenta")],
}

MANUAL_REVIEW_EDITS: dict[str, tuple[str, str, str]] = {
    "0x00061e4d": (
        "cavaleiro errante, caçador de bruxas, não um bruxo",
        "cavaleira errante, caçadora de bruxas, não uma bruxa",
        "o trecho pode descrever a própria personagem ou um arquétipo genérico",
    ),
    "0x000fe845": (
        "Inteiramente molhado.",
        "Inteiramente molhada.",
        "fala isolada; é preciso confirmar pelo áudio/cena se descreve a personagem",
    ),
}


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char))
        .lower()
        .split()
    )


def preserve_case(original: str, replacement: str) -> str:
    if original.isupper():
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def clean_spacing(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    text = re.sub(r"([.!?…])(?=[A-Za-zÀ-ÖØ-öø-ÿ])", r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"^[,;:]\s*", "", text)
    return text


def clean_vocal_actions(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    capitalization_marker = "\uFFF0"

    def replace_star(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        token = normalized(content)
        if token in ACTION_TERMS or all(part in {"cof", "sniff", "snif"} for part in token.split()):
            notes.append(f"ação removida: {content}")
            return " "
        notes.append(f"marcação removida, texto preservado: {content}")
        return content

    edited = STAR_RE.sub(replace_star, text)
    vocal_tokens = [match.group(0) for match in VOCAL_RE.finditer(edited)]

    def replace_vocal(match: re.Match[str]) -> str:
        before = edited[:match.start()].rstrip()
        begins_new_phrase = not before or before.endswith((".", "!", "?", "…", "--"))
        return " " + (capitalization_marker if begins_new_phrase else "") + " "

    edited = VOCAL_WITH_PUNCT_RE.sub(replace_vocal, edited)
    if vocal_tokens:
        notes.append("vocalização escrita removida: " + ", ".join(vocal_tokens))
        # A vocalização costuma vir acompanhada de sua própria pontuação.
        # Depois de retirar a palavra, remove apenas a pontuação que ficou
        # órfã nas bordas e colapsa pares como ". !" ou ", ," no meio.
        edited = re.sub(r"^(?:\s*[,.;:!?…—-]+\s*)+", "", edited)
        edited = re.sub(r"(?:\s+[,.;:!?…—-]+\s*)+$", "", edited)
        edited = re.sub(r"([,.;:!?…])\s+[,.;:!?…—-]+", r"\1", edited)
    cleaned = clean_spacing(edited)
    if vocal_tokens:
        cleaned = re.sub(r"\s*--+\s*", "... ", cleaned)

        def capitalize_marked(match: re.Match[str]) -> str:
            return match.group(1).upper()

        cleaned = re.sub(
            capitalization_marker + r"\s*([a-zà-öø-ÿ])",
            capitalize_marked,
            cleaned,
        )
        cleaned = clean_spacing(cleaned.replace(capitalization_marker, ""))
    return cleaned, notes


def manual_gender_proposal(ident: str, text: str) -> tuple[str, list[str]]:
    edited = text
    notes: list[str] = []
    for old, new in MANUAL_GENDER_EDITS.get(ident, []):
        if old not in edited:
            raise PortugueseAuditError(
                f"{ident}: trecho esperado ausente na auditoria manual: {old!r}"
            )
        edited = edited.replace(old, new)
        notes.append(f"{old}→{new} (contexto confirmado por ID)")
    return edited, notes


def gender_proposal(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    edited = text

    def replace_same(match: re.Match[str]) -> str:
        notes.append("mesmo→mesma em autorreferência explícita")
        return f"{match.group('subject')} mesma"

    edited = SAME_RE.sub(replace_same, edited)

    def replace_first_person(match: re.Match[str]) -> str:
        word = match.group("word")
        replacement = GENDER_PAIRS.get(word.lower())
        if replacement is None or replacement == word.lower():
            return match.group(0)
        prefix = match.group("prefix")
        article = match.group("article") or ""
        if article.lower() in {"um", "o", "esse", "aquele"}:
            article = {"um": "uma", "o": "a", "esse": "essa", "aquele": "aquela"}[article.lower()]
        replacement = preserve_case(word, replacement)
        notes.append(f"{word}→{replacement} após gatilho de primeira pessoa")
        middle = f" {article}" if article else ""
        return f"{prefix}{middle} {replacement}"

    edited = FIRST_PERSON_RE.sub(replace_first_person, edited)
    return edited, notes


def read_manifest(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PortugueseAuditError(f"manifesto não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "texto_original", "texto_final"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise PortugueseAuditError("manifesto incompatível")
        return list(reader)


def audit_row(row: dict[str, str]) -> list[Finding]:
    ident = (row.get("id_hex") or "").strip().lower()
    action = (row.get("acao") or "").strip().lower()
    original = (row.get("texto_original") or "").strip()
    text = (row.get("texto_final") if "texto_final" in row else original).strip()
    findings: list[Finding] = []

    original_markers = [match.group(1).strip() for match in STAR_RE.finditer(original)]
    final_markers = [match.group(1).strip() for match in STAR_RE.finditer(text)]
    if original_markers and not final_markers:
        findings.append(
            Finding(
                ident,
                "marcacao_ja_tratada",
                "informativa",
                original,
                text,
                "nenhuma",
                "marcação removida na preparação: " + ", ".join(original_markers),
            )
        )

    if action != "gerar":
        return findings

    cleaned, vocal_notes = clean_vocal_actions(text)
    if vocal_notes:
        pure_action = not cleaned or not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]{2,}", cleaned)
        findings.append(
            Finding(
                ident,
                "vocalizacao_ou_acao",
                "alta",
                text,
                "" if pure_action else cleaned,
                "usar_original" if pure_action else "gerar",
                "; ".join(vocal_notes)
                + ("; fala sem conteúdo verbal restante" if pure_action else ""),
            )
        )

    gender_base = cleaned if vocal_notes else text
    manually_gendered, manual_gender_notes = manual_gender_proposal(ident, gender_base)
    gendered, generic_gender_notes = gender_proposal(manually_gendered)
    gender_notes = manual_gender_notes + generic_gender_notes
    if gender_notes:
        findings.append(
            Finding(
                ident,
                "concordancia_feminina",
                "alta",
                gender_base,
                gendered,
                "gerar",
                "; ".join(gender_notes),
            )
        )

    if ident in MANUAL_REVIEW_EDITS:
        old, new, detail = MANUAL_REVIEW_EDITS[ident]
        if old not in text:
            raise PortugueseAuditError(
                f"{ident}: trecho esperado ausente na revisão contextual: {old!r}"
            )
        findings.append(
            Finding(
                ident,
                "concordancia_contextual",
                "media",
                text,
                text.replace(old, new),
                "revisar",
                detail,
            )
        )

    # Casos de artigo masculino antes de termos femininos conhecidos geralmente
    # indicam uma substituição parcial e precisam de contexto antes de editar.
    if re.search(
        r"\b(?:um|o|esse|seu|nenhum)\s+(?:bruxa|amiga|bandida|assassina|"
        r"inimiga|aluna|forasteira|convidada|criada|prisioneira|soldada)\b",
        text,
        re.IGNORECASE,
    ):
        findings.append(
            Finding(
                ident,
                "concordancia_suspeita",
                "media",
                text,
                "",
                "revisar",
                "artigo ou possessivo masculino antes de termo feminino",
            )
        )
    return findings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--safe-corrections", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows = read_manifest(args.manifest)
        findings = [finding for row in rows for finding in audit_row(row)]
        findings.sort(key=lambda item: (int(item.ident, 0), item.category))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        headers = [
            "id_hex", "categoria", "confianca", "texto_atual", "texto_proposto",
            "acao_proposta", "detalhe",
        ]
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(headers)
            for item in findings:
                writer.writerow(
                    [item.ident, item.category, item.confidence, item.current_text,
                     item.proposed_text, item.proposed_action, item.detail]
                )

        # Consolida por ID: ação vocal segura primeiro e concordância feminina
        # sobre o texto já limpo. Casos de revisão nunca entram automaticamente.
        safe_by_id: dict[str, Finding] = {}
        for item in findings:
            if item.confidence != "alta" or item.proposed_action not in {"gerar", "usar_original"}:
                continue
            current = safe_by_id.get(item.ident)
            if current is None:
                safe_by_id[item.ident] = item
            elif current.proposed_action == "gerar" and item.proposed_action == "gerar":
                # A segunda proposta (gênero) já parte do texto vocalmente limpo.
                safe_by_id[item.ident] = Finding(
                    item.ident, "vocalizacao_e_genero", "alta", current.current_text,
                    item.proposed_text, "gerar", current.detail + "; " + item.detail,
                )
            elif item.proposed_action == "usar_original":
                safe_by_id[item.ident] = item

        args.safe_corrections.parent.mkdir(parents=True, exist_ok=True)
        with args.safe_corrections.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "acao", "texto", "motivo"])
            for item in sorted(safe_by_id.values(), key=lambda value: int(value.ident, 0)):
                writer.writerow(
                    [item.ident, item.proposed_action, item.proposed_text,
                     "Auditoria de português: " + item.detail + "."]
                )

        review_items = [item for item in findings if item.proposed_action == "revisar"]
        args.review.parent.mkdir(parents=True, exist_ok=True)
        with args.review.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(headers)
            for item in review_items:
                writer.writerow(
                    [item.ident, item.category, item.confidence, item.current_text,
                     item.proposed_text, item.proposed_action, item.detail]
                )
        categories: dict[str, int] = {}
        for item in findings:
            categories[item.category] = categories.get(item.category, 0) + 1
        print(f"Falas no manifesto: {len(rows)}")
        print(f"Achados: {len(findings)}")
        print("Categorias: " + ", ".join(f"{key}={value}" for key, value in sorted(categories.items())))
        print(f"Correções seguras por ID: {len(safe_by_id)}")
        print(f"Casos para revisão: {len(review_items)}")
        print(f"Relatório: {args.report}")
        print(f"Correções: {args.safe_corrections}")
        print(f"Revisão: {args.review}")
        return 0
    except (PortugueseAuditError, OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
