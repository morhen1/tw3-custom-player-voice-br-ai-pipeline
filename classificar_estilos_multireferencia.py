#!/usr/bin/env python3
"""Classifica falas em estilos expressivos com pontuação e fila de revisão."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


class ClassificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class StyleDefinition:
    ident: str
    description: str
    delivery: str
    reference_status: str


STYLES = (
    StyleDefinition(
        "alerta_tenso",
        "Reação curta a perigo, surpresa ou hesitação.",
        "Ataque rápido, tensão audível e pouca preparação.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "combate_agressivo",
        "Ameaça, ordem de combate ou ação violenta imediata.",
        "Energia alta, articulação firme e raiva controlada.",
        "pendente_candidato",
    ),
    StyleDefinition(
        "confronto_firme",
        "Cobrança, acusação ou imposição direta.",
        "Autoridade e firmeza sem transformar a fala em grito.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "investigacao_observacional",
        "Leitura de pistas, rastros e ambiente.",
        "Tom atento, contido e com pausas funcionais.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "tristeza_contida",
        "Luto, culpa, despedida ou sofrimento pessoal.",
        "Emoção perceptível, baixa intensidade e sem melodrama.",
        "pendente_candidato",
    ),
    StyleDefinition(
        "ironia_seca",
        "Provocação, sarcasmo ou humor discreto.",
        "Leve sorriso vocal e pausas deliberadas.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "pergunta_cautelosa",
        "Pergunta conversacional sem perigo imediato.",
        "Curiosidade natural, intensidade baixa ou média.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "narrativa_contida",
        "Explicação longa, raciocínio ou exposição de contexto.",
        "Cadência estável e pausas sintáticas, sem pressa.",
        "aprovada_piloto",
    ),
    StyleDefinition(
        "conversa_neutra",
        "Fala cotidiana sem emoção dominante.",
        "Naturalidade, clareza e intensidade moderada.",
        "aprovada_piloto",
    ),
)

STYLE_BY_ID = {style.ident: style for style in STYLES}
STYLE_ORDER = {style.ident: index for index, style in enumerate(STYLES)}


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_marks.lower()).strip()


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{8}", token):
        raise ClassificationError(f"ID inválido: {value}")
    return token


def parse_duration(value: str) -> float:
    token = (value or "").strip().replace(",", ".")
    if not token:
        return 0.0
    try:
        result = float(token)
    except ValueError as exc:
        raise ClassificationError(f"duração inválida: {value}") from exc
    if result < 0 or not math.isfinite(result):
        raise ClassificationError(f"duração inválida: {value}")
    return result


def count_matches(text: str, fragments: tuple[tuple[str, float], ...]) -> tuple[float, list[str]]:
    score = 0.0
    found: list[str] = []
    for fragment, weight in fragments:
        prefix = fragment.endswith("*")
        token = fragment[:-1] if prefix else fragment
        pattern = rf"(?<!\w){re.escape(token)}{'\\w*' if prefix else ''}(?!\w)"
        if re.search(pattern, text):
            score += weight
            found.append(token)
    return score, found


INVESTIGATION = (
    ("pegada*", 3.5), ("rastro*", 3.5), ("vestigio*", 3.0), ("pista*", 3.0),
    ("sangue", 2.0), ("cheiro*", 2.0), ("cadaver*", 2.5), ("corpo*", 1.2),
    ("ferida*", 1.5), ("mordida*", 2.0), ("garra*", 2.0), ("marca*", 1.0),
    ("monstro*", 1.8), ("criatura*", 1.5), ("ninho*", 2.0), ("caverna*", 1.6),
    ("trancad*", 2.0), ("fechadura*", 2.0), ("outro caminho", 2.0),
    ("anotac*", 2.0), ("ritual*", 1.5), ("veneno*", 1.5), ("fresco*", 1.0),
    ("examin*", 2.5), ("investig*", 2.5), ("raciocinio*", 1.5), ("teoria*", 1.2),
)

COMBAT = (
    ("ataque", 2.5), ("ataquem", 3.5), ("mate", 3.5), ("matem", 3.5),
    ("vou te matar", 5.0), ("vou mata*", 4.0), ("morra", 4.5),
    ("acabe com", 3.0), ("nao vai escapar", 3.5), ("nao escapara", 3.5),
    ("prepare se", 2.5), ("saque a espada", 3.0), ("largue a espada", 2.5),
    ("lutar", 1.0), ("luta", 0.8), ("batalha*", 0.8), ("combate*", 1.0),
    ("espada*", 0.5), ("fique atras de mim", 3.0), ("cubram", 2.5),
    ("cercad*", 1.5), ("emboscada*", 1.0), ("inimigo*", 1.2),
)

SADNESS_STRONG = (
    ("sinto muito", 4.5), ("me desculpe", 4.0), ("perdao", 3.5),
    ("sinto falta", 5.0), ("saudades", 4.0), ("nao pude salvar", 5.0),
    ("nao consegui salvar", 5.0), ("foi minha culpa", 5.0), ("e minha culpa", 5.0),
    ("nunca vou esquecer", 4.0), ("descanse em paz", 4.5), ("va em paz", 3.5),
    ("adeus", 3.0), ("perdi ", 3.0), ("eu falhei", 4.0),
)

SADNESS_WEAK = (
    ("morreu", 1.0), ("morto*", 0.8), ("morta*", 0.8), ("dor", 0.8),
    ("sofr*", 1.0), ("chor*", 1.2), ("lamento", 2.0), ("triste*", 2.0),
)

IRONY = (
    ("que surpresa", 3.5), ("muito engracado", 3.5), ("gracinha", 3.0),
    ("piada*", 1.0), ("brincando", 1.2), ("astucia", 3.0),
    ("digno de", 2.0), ("claro que", 0.8), ("imagino", 1.3),
    ("suponho", 1.3), ("e mesmo", 1.5), ("por acaso", 1.2),
    ("digo nos", 2.5), ("interacao mais intima", 3.0),
    ("maravilha", 1.2), ("otimo", 0.8),
)

CONFRONTATION = (
    ("como ousa", 4.0), ("voce mentiu", 4.0), ("esta mentindo", 3.5),
    ("diga a verdade", 4.0), ("nao acredito em voce", 3.5),
    ("responda", 2.5), ("confesse", 3.5), ("explique", 2.0),
    ("por que voce", 2.2), ("o que voce fez", 2.5), ("acordo com", 1.0),
    ("nilfgaard", 0.5), ("afaste se", 2.5), ("pare agora", 3.0),
    ("nao vou permitir", 3.0), ("nao permitirei", 3.0),
)

ALERT = (
    ("cuidado", 4.0), ("fique alerta", 4.0), ("atencao", 3.0),
    ("algo esta", 1.2), ("ouviu isso", 2.5), ("o que foi isso", 2.5),
    ("ali ", 1.2), ("depressa", 2.0), ("rapido", 1.5),
    ("estamos cercad*", 3.5), ("esta perto", 2.0),
)


def add_fragments(
    scores: dict[str, float],
    reasons: dict[str, list[str]],
    style: str,
    normalized: str,
    fragments: tuple[tuple[str, float], ...],
    label: str,
) -> None:
    score, found = count_matches(normalized, fragments)
    if score:
        scores[style] += score
        reasons[style].append(f"{label}: " + ", ".join(found[:6]))


def score_styles(text: str, duration: float) -> tuple[dict[str, float], dict[str, list[str]], dict[str, object]]:
    normalized = normalize_text(text)
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text)
    word_count = len(words)
    question = "?" in text
    exclamation = "!" in text
    ellipsis = "..." in text or "…" in text
    sentence_count = max(1, len(re.findall(r"[.!?]+", text)))
    density = word_count / duration if duration > 0 else 0.0

    scores = {style.ident: 0.0 for style in STYLES}
    reasons: dict[str, list[str]] = defaultdict(list)
    scores["conversa_neutra"] = 1.0
    if 4 <= word_count <= 22 and not exclamation:
        scores["conversa_neutra"] += 0.5

    add_fragments(scores, reasons, "investigacao_observacional", normalized, INVESTIGATION, "pistas")
    add_fragments(scores, reasons, "combate_agressivo", normalized, COMBAT, "combate")
    add_fragments(scores, reasons, "tristeza_contida", normalized, SADNESS_STRONG, "emoção pessoal")
    add_fragments(scores, reasons, "tristeza_contida", normalized, SADNESS_WEAK, "emoção contextual")
    add_fragments(scores, reasons, "ironia_seca", normalized, IRONY, "ironia")
    add_fragments(scores, reasons, "confronto_firme", normalized, CONFRONTATION, "confronto")
    add_fragments(scores, reasons, "alerta_tenso", normalized, ALERT, "alerta")

    if "nao me sinto muito" in normalized or "me sinto muito" in normalized:
        scores["tristeza_contida"] = max(0.0, scores["tristeza_contida"] - 4.5)
        reasons["tristeza_contida"].append("uso não emocional de 'me sinto muito' descontado")
    if "de acordo com" in normalized:
        scores["confronto_firme"] = max(0.0, scores["confronto_firme"] - 1.0)
        reasons["confronto_firme"].append("expressão neutra 'de acordo com' descontada")

    if word_count >= 25:
        scores["narrativa_contida"] += 3.0 + min(2.0, (word_count - 25) / 18.0)
        reasons["narrativa_contida"].append(f"fala longa: {word_count} palavras")
    if duration >= 8.0:
        scores["narrativa_contida"] += 2.5 + min(1.5, (duration - 8.0) / 8.0)
        reasons["narrativa_contida"].append(f"duração oficial: {duration:.2f}s")
    if sentence_count >= 3 and word_count >= 18:
        scores["narrativa_contida"] += 1.2
        reasons["narrativa_contida"].append(f"{sentence_count} segmentos sintáticos")

    if question:
        scores["pergunta_cautelosa"] += 2.4
        reasons["pergunta_cautelosa"].append("interrogação")
        if word_count <= 4:
            scores["alerta_tenso"] += 2.0
            reasons["alerta_tenso"].append("pergunta muito curta")
        elif ellipsis and word_count <= 8:
            scores["alerta_tenso"] += 1.5
            reasons["alerta_tenso"].append("pergunta curta hesitante")
    if exclamation:
        scores["alerta_tenso"] += 1.5
        scores["combate_agressivo"] += 0.8
        reasons["alerta_tenso"].append("exclamação")
    if ellipsis:
        scores["ironia_seca"] += 0.4
        reasons["ironia_seca"].append("reticências")
    if density >= 8.5 and duration > 0:
        scores["alerta_tenso"] += 0.8
        reasons["alerta_tenso"].append(f"ritmo textual alto: {density:.1f} palavras/s")
    if word_count <= 3 and duration <= 1.5 and not question:
        scores["alerta_tenso"] += 0.8
        reasons["alerta_tenso"].append("reação curta")

    # Palavras de morte isoladas costumam pertencer a investigações, não a luto.
    if scores["tristeza_contida"] <= 1.2 and scores["investigacao_observacional"] >= 2.5:
        scores["tristeza_contida"] *= 0.35
    if question and scores["confronto_firme"] >= 2.0:
        scores["confronto_firme"] += 0.8
        reasons["confronto_firme"].append("cobrança interrogativa")

    features = {
        "palavras": word_count,
        "pergunta": question,
        "exclamacao": exclamation,
        "reticencias": ellipsis,
        "segmentos": sentence_count,
        "palavras_por_s": density,
    }
    return scores, reasons, features


def classify(
    ident: str,
    text: str,
    duration: float,
    pilot: dict[str, str],
) -> dict[str, object]:
    scores, reasons, features = score_styles(text, duration)
    if ident in pilot:
        style = pilot[ident]
        if style not in STYLE_BY_ID:
            raise ClassificationError(f"estilo do piloto desconhecido: {style}")
        ordered = sorted(scores, key=lambda key: (-scores[key], STYLE_ORDER[key]))
        second = next((item for item in ordered if item != style), "conversa_neutra")
        return {
            "estilo": style,
            "segunda_opcao": second,
            "confianca": "alta",
            "pontuacao": 99.0,
            "margem": 99.0,
            "criterios": "classificação confirmada no piloto de 20 falas",
            "revisar": "não",
            "prioridade": "nenhuma",
            "origem": "piloto_confirmado",
            "scores": scores,
            "features": features,
        }

    specific = [style.ident for style in STYLES if style.ident != "conversa_neutra"]
    best_specific = max(specific, key=lambda key: (scores[key], -STYLE_ORDER[key]))
    if scores[best_specific] < 2.0:
        style = "conversa_neutra"
    else:
        style = best_specific
    ordered = sorted(scores, key=lambda key: (-scores[key], STYLE_ORDER[key]))
    second = next((item for item in ordered if item != style), "conversa_neutra")
    top_score = scores[style]
    second_score = scores[second]
    margin = top_score - second_score

    if style == "conversa_neutra":
        strongest_specific = scores[best_specific]
        confidence = "media" if strongest_specific < 1.5 else "baixa"
    elif top_score >= 5.0 and margin >= 2.0:
        confidence = "alta"
    elif top_score >= 2.3 and margin >= 0.70:
        confidence = "media"
    else:
        confidence = "baixa"

    review = "não"
    priority = "nenhuma"
    if style != "conversa_neutra" and margin < 0.35:
        review, priority = "sim", "alta"
    elif style != "conversa_neutra" and confidence == "baixa":
        review, priority = "sim", "media"
    elif style == "conversa_neutra" and scores[best_specific] >= 1.9:
        review, priority = "sim", "baixa"

    criteria = reasons.get(style, [])
    if style == "conversa_neutra" and not criteria:
        criteria = ["nenhum gatilho expressivo dominante"]
    return {
        "estilo": style,
        "segunda_opcao": second,
        "confianca": confidence,
        "pontuacao": top_score,
        "margem": margin,
        "criterios": " | ".join(criteria),
        "revisar": review,
        "prioridade": priority,
        "origem": "regras_semanticas_duracao",
        "scores": scores,
        "features": features,
    }


def read_pilot(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames or not {"id_hex", "estilo"}.issubset(reader.fieldnames):
            raise ClassificationError("piloto deve conter id_hex;estilo")
        result: dict[str, str] = {}
        for row in reader:
            ident = normalize_id(row.get("id_hex") or "")
            style = (row.get("estilo") or "").strip()
            if ident in result:
                raise ClassificationError(f"ID repetido no piloto: {ident}")
            result[ident] = style
        return result


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "texto_original", "texto_final", "duracao_original"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ClassificationError("manifesto sem as colunas obrigatórias")
        rows = list(reader)
    seen: set[str] = set()
    for row in rows:
        ident = normalize_id(row.get("id_hex") or "")
        if ident in seen:
            raise ClassificationError(f"ID repetido no manifesto: {ident}")
        seen.add(ident)
        row["id_hex"] = ident
    return rows


OUTPUT_FIELDS = [
    "id_hex", "texto", "acao", "duracao_original_s", "palavras", "marcadores",
    "estilo", "segunda_opcao", "confianca", "pontuacao_topo", "margem",
    "criterios", "revisar", "prioridade_revisao", "status_referencia",
    "origem_classificacao", "pontuacoes",
]


def write_dicts(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def candidate_quality(row: dict[str, object]) -> float:
    duration = float(row["duracao_original_s"])
    words = int(row["palavras"])
    style = str(row["estilo"])
    target = 9.0 if style == "narrativa_contida" else 4.0
    duration_fit = max(0.0, 3.0 - abs(duration - target) * 0.45)
    word_fit = 1.5 if 5 <= words <= 22 else 0.0
    return float(row["pontuacao_topo"]) + float(row["margem"]) + duration_fit + word_fit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pilot-assignments", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assignments-output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--review-jsonl-output", type=Path, required=True)
    parser.add_argument("--catalog-output", type=Path, required=True)
    parser.add_argument("--candidates-output", type=Path, required=True)
    parser.add_argument("--candidates-per-style", type=int, default=12)
    args = parser.parse_args()
    try:
        if args.candidates_per_style < 1:
            raise ClassificationError("--candidates-per-style deve ser positivo")
        manifest = read_manifest(args.manifest)
        pilot = read_pilot(args.pilot_assignments)
        rows: list[dict[str, object]] = []
        excluded = 0
        for source in manifest:
            action = (source.get("acao") or "").strip().lower()
            if action != "gerar":
                excluded += 1
                continue
            ident = source["id_hex"]
            text = (source.get("texto_final") or source.get("texto_original") or "").strip()
            if not text:
                raise ClassificationError(f"texto vazio em {ident}")
            duration = parse_duration(source.get("duracao_original") or "")
            result = classify(ident, text, duration, pilot)
            features = result["features"]
            markers = []
            if features["pergunta"]:
                markers.append("pergunta")
            if features["exclamacao"]:
                markers.append("exclamacao")
            if features["reticencias"]:
                markers.append("reticencias")
            scores = result["scores"]
            rows.append({
                "id_hex": ident,
                "texto": text,
                "acao": action,
                "duracao_original_s": round(duration, 6),
                "palavras": features["palavras"],
                "marcadores": "|".join(markers) or "declarativa",
                "estilo": result["estilo"],
                "segunda_opcao": result["segunda_opcao"],
                "confianca": result["confianca"],
                "pontuacao_topo": round(float(result["pontuacao"]), 2),
                "margem": round(float(result["margem"]), 2),
                "criterios": result["criterios"],
                "revisar": result["revisar"],
                "prioridade_revisao": result["prioridade"],
                "status_referencia": STYLE_BY_ID[str(result["estilo"])].reference_status,
                "origem_classificacao": result["origem"],
                "pontuacoes": "|".join(
                    f"{style.ident}:{float(scores[style.ident]):.2f}" for style in STYLES
                ),
            })

        manifest_ids = {row["id_hex"] for row in manifest}
        unknown_pilot = sorted(set(pilot) - manifest_ids)
        if unknown_pilot:
            raise ClassificationError(
                "IDs do piloto ausentes do manifesto: " + ", ".join(unknown_pilot[:10])
            )
        rows.sort(key=lambda row: int(str(row["id_hex"]), 0))
        write_dicts(args.output, OUTPUT_FIELDS, rows)

        args.assignments_output.parent.mkdir(parents=True, exist_ok=True)
        with args.assignments_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "estilo"])
            writer.writerows((row["id_hex"], row["estilo"]) for row in rows)

        priority_order = {"alta": 0, "media": 1, "baixa": 2, "nenhuma": 3}
        reviews = sorted(
            (row for row in rows if row["revisar"] == "sim"),
            key=lambda row: (
                priority_order[str(row["prioridade_revisao"])],
                float(row["margem"]),
                int(str(row["id_hex"]), 0),
            ),
        )
        write_dicts(args.review_output, OUTPUT_FIELDS, reviews)
        args.review_jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        with args.review_jsonl_output.open("w", encoding="utf-8", newline="\n") as handle:
            for row in reviews:
                handle.write(
                    json.dumps(
                        {"id": row["id_hex"], "text": row["texto"]},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        counts = Counter(str(row["estilo"]) for row in rows)
        confidence_counts: dict[str, Counter[str]] = defaultdict(Counter)
        review_counts = Counter()
        for row in rows:
            confidence_counts[str(row["estilo"])][str(row["confianca"])] += 1
            if row["revisar"] == "sim":
                review_counts[str(row["estilo"])] += 1
        catalog_rows: list[dict[str, object]] = []
        for style in STYLES:
            catalog_rows.append({
                "estilo": style.ident,
                "descricao": style.description,
                "entrega_esperada": style.delivery,
                "status_referencia": style.reference_status,
                "falas": counts[style.ident],
                "percentual": round(counts[style.ident] / max(1, len(rows)), 6),
                "confianca_alta": confidence_counts[style.ident]["alta"],
                "confianca_media": confidence_counts[style.ident]["media"],
                "confianca_baixa": confidence_counts[style.ident]["baixa"],
                "revisar": review_counts[style.ident],
            })
        write_dicts(
            args.catalog_output,
            ["estilo", "descricao", "entrega_esperada", "status_referencia", "falas", "percentual", "confianca_alta", "confianca_media", "confianca_baixa", "revisar"],
            catalog_rows,
        )

        candidate_rows: list[dict[str, object]] = []
        for style in STYLES:
            eligible = [
                row for row in rows
                if row["estilo"] == style.ident
                and row["origem_classificacao"] != "piloto_confirmado"
                and 1.2 <= float(row["duracao_original_s"]) <= (14.0 if style.ident == "narrativa_contida" else 7.5)
                and int(row["palavras"]) >= 4
            ]
            eligible.sort(key=lambda row: (-candidate_quality(row), int(str(row["id_hex"]), 0)))
            for rank, row in enumerate(eligible[: args.candidates_per_style], start=1):
                candidate_rows.append({
                    "estilo": style.ident,
                    "rank": rank,
                    "id_hex": row["id_hex"],
                    "texto": row["texto"],
                    "duracao_original_s": row["duracao_original_s"],
                    "confianca": row["confianca"],
                    "pontuacao_topo": row["pontuacao_topo"],
                    "margem": row["margem"],
                    "criterios": row["criterios"],
                    "status_referencia": style.reference_status,
                })
        write_dicts(
            args.candidates_output,
            ["estilo", "rank", "id_hex", "texto", "duracao_original_s", "confianca", "pontuacao_topo", "margem", "criterios", "status_referencia"],
            candidate_rows,
        )

        print(f"Manifesto: {len(manifest)}; classificadas: {len(rows)}; excluídas: {excluded}")
        print("Estilos: " + ", ".join(f"{style.ident}={counts[style.ident]}" for style in STYLES))
        print(
            "Confiança: "
            + ", ".join(
                f"{level}={sum(1 for row in rows if row['confianca'] == level)}"
                for level in ("alta", "media", "baixa")
            )
        )
        print(
            "Revisão: "
            + ", ".join(
                f"{level}={sum(1 for row in reviews if row['prioridade_revisao'] == level)}"
                for level in ("alta", "media", "baixa")
            )
        )
        print(f"Classificação: {args.output}")
        print(f"Atribuições: {args.assignments_output}")
        print(f"Fila de revisão: {args.review_output}")
        print(f"JSONL acústico: {args.review_jsonl_output}")
        print(f"Catálogo: {args.catalog_output}")
        print(f"Candidatas: {args.candidates_output}")
        return 0
    except (ClassificationError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
