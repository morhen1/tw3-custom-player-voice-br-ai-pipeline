#!/usr/bin/env python3
"""Extrai candidatos a nomes próprios do JSONL efetivamente enviado ao OmniVoice."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’\-]*")
GERALT_RE = re.compile(r"\bGeralt\b", re.IGNORECASE)
SENTENCE_BOUNDARY_RE = re.compile(r"(?:^|[.!?…]\s*[\"'“”‘’(\[]*)$")

CONNECTORS = {
    "a", "an", "da", "das", "de", "do", "dos", "du", "la", "le",
    "of", "the", "van", "var", "von",
}

# Palavras comuns que aparecem em maiúscula por iniciarem frase, citação ou opção.
STOPWORDS = {
    "a", "ah", "ainda", "algo", "alguma", "algumas", "algum", "alguns",
    "antes", "ao", "aos", "aqui", "as", "assim", "até", "bem", "boa",
    "bom", "certo", "claro", "como", "com", "continue", "contra", "da",
    "das", "de", "depois", "desde", "deus", "diga", "do", "dos", "e",
    "ela", "ele", "eles", "em", "então", "era", "essa", "esse", "esta",
    "está", "este", "estou", "eu", "exato", "faça", "fale", "finalmente",
    "foi", "há", "hm", "hmm", "isso", "isto", "já", "mas", "me", "meu",
    "minha", "muito", "na", "nada", "não", "nas", "nem", "no", "nos",
    "nós", "nossa", "o", "obrigada", "olá", "onde", "os", "ou", "para",
    "pare", "pelo", "pelos", "por", "porque", "pra", "pode", "pois",
    "qual", "quando", "que", "quem", "se", "sem", "será", "seu", "sim",
    "só", "sobre", "sou", "talvez", "também", "tem", "tenho", "tudo",
    "um", "uma", "vá", "vamos", "você", "vocês",
}


def normalize_term(term: str) -> str:
    return " ".join(term.replace("’", "'").split())


def is_sentence_start(text: str, start: int) -> bool:
    return bool(SENTENCE_BOUNDARY_RE.search(text[:start]))


def extract_candidates(text: str) -> list[str]:
    matches = list(TOKEN_RE.finditer(text))
    candidates: list[str] = []
    index = 0
    while index < len(matches):
        match = matches[index]
        word = match.group(0)
        capitalized = word[:1].isupper()
        sentence_start = is_sentence_start(text, match.start())
        if not capitalized:
            index += 1
            continue

        parts = [word]
        end_index = index
        cursor = index + 1
        while cursor < len(matches):
            between = text[matches[cursor - 1].end():matches[cursor].start()]
            if not re.fullmatch(r"[\s,]*", between):
                break
            next_word = matches[cursor].group(0)
            lower = next_word.casefold()
            if lower in CONNECTORS:
                if cursor + 1 >= len(matches):
                    break
                between2 = text[matches[cursor].end():matches[cursor + 1].start()]
                after = matches[cursor + 1].group(0)
                if not re.fullmatch(r"\s+", between2) or not after[:1].isupper():
                    break
                parts.extend([next_word, after])
                end_index = cursor + 1
                cursor += 2
                continue
            if next_word[:1].isupper():
                parts.append(next_word)
                end_index = cursor
                cursor += 1
                continue
            break

        # Artigos capitalizados antes de nomes geram variantes como "O Dandelion".
        if len(parts) > 1 and parts[0].casefold() in {"a", "as", "o", "os"}:
            parts = parts[1:]
        phrase = normalize_term(" ".join(parts))
        head = parts[0].casefold()
        # Frases com dois elementos capitalizados são fortes candidatas. Para
        # termos únicos, exigimos posição interna ou palavra não comum.
        has_multiple_names = sum(p[:1].isupper() for p in parts) >= 2
        if has_multiple_names or (head not in STOPWORDS and not sentence_start):
            candidates.append(phrase)
        elif head not in STOPWORDS and len(word) >= 3:
            # Mantém o candidato de início de frase, mas a etapa agregada exige
            # evidência adicional (recorrência ou ocorrência interna).
            candidates.append(phrase)
        index = max(index + 1, end_index + 1)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    geralt_rows: list[dict[str, str]] = []
    total = 0
    rows: list[tuple[str, str]] = []
    token_total: Counter[str] = Counter()
    token_capitalized: Counter[str] = Counter()
    token_mid_sentence: Counter[str] = Counter()

    with args.jsonl.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            payload = json.loads(raw)
            ident = str(payload["id"]).lower()
            text = str(payload["text"])
            total += 1
            rows.append((ident, text))
            for match in TOKEN_RE.finditer(text):
                word = match.group(0)
                key = word.casefold()
                token_total[key] += 1
                if word[:1].isupper():
                    token_capitalized[key] += 1
                    if not is_sentence_start(text, match.start()):
                        token_mid_sentence[key] += 1
            if GERALT_RE.search(text):
                geralt_rows.append({
                    "id_hex": ident,
                    "texto_atual": text,
                    "texto_proposto": GERALT_RE.sub("Geralda", text),
                    "ocorrencias": str(len(GERALT_RE.findall(text))),
                })
    for ident, text in rows:
        for term in set(extract_candidates(text)):
            counts[term] += 1
            if len(examples[term]) < 5:
                examples[term].append({"id_hex": ident, "texto": text})

    # Remove candidatos extremamente fracos: termo único, apenas uma vez e
    # capitalizado somente porque inicia a frase.
    candidates = []
    for term, count in counts.most_common():
        parts = [part for part in term.split() if part.casefold() not in CONNECTORS]
        main_keys = [part.casefold() for part in parts]
        if not main_keys or any(key in STOPWORDS for key in main_keys):
            continue
        capitalization_ratios = [
            token_capitalized[key] / token_total[key] for key in main_keys
        ]
        has_mid_sentence_evidence = any(token_mid_sentence[key] for key in main_keys)
        # Nomes próprios permanecem capitalizados no corpus. Esta razão elimina
        # verbos/adjetivos que só ficaram maiúsculos por iniciarem frases.
        minimum_ratio = 0.78 if len(main_keys) == 1 else 0.68
        if min(capitalization_ratios) < minimum_ratio:
            continue
        if not has_mid_sentence_evidence and count < 2:
            continue
        candidates.append({
            "termo": term,
            "ocorrencias_linhas": count,
            "razao_maiusculas_min": round(min(capitalization_ratios), 4),
            "evidencia_interna": has_mid_sentence_evidence,
            "exemplos": examples[term],
        })

    result = {
        "fonte": str(args.jsonl.resolve()),
        "falas": total,
        "geralt": {
            "linhas": len(geralt_rows),
            "ocorrencias": sum(int(row["ocorrencias"]) for row in geralt_rows),
            "registros": geralt_rows,
        },
        "candidatos": candidates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Falas: {total}")
    print(f"Geralt: {len(geralt_rows)} linhas; {result['geralt']['ocorrencias']} ocorrências")
    print(f"Candidatos: {len(candidates)}")
    print(f"Saída: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
