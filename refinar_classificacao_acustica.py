#!/usr/bin/env python3
"""Usa prosódia oficial para desempatar uma classificação multirreferência."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


class RefinementError(RuntimeError):
    pass


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames:
            raise RefinementError(f"CSV sem cabeçalho: {path}")
        return list(reader.fieldnames), list(reader)


def by_id(path: Path) -> dict[str, dict[str, str]]:
    _, rows = read_csv(path)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        ident = (row.get("id_hex") or "").strip().lower()
        if not ident:
            continue
        if ident in result:
            raise RefinementError(f"ID repetido em {path}: {ident}")
        result[ident] = row
    return result


def parse_scores(value: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in value.split("|"):
        if not item:
            continue
        key, separator, raw = item.partition(":")
        if not separator:
            raise RefinementError(f"pontuações inválidas: {value}")
        try:
            result[key] = float(raw)
        except ValueError as exc:
            raise RefinementError(f"pontuação inválida: {item}") from exc
    return result


def acoustic_support(style: str, metric: dict[str, str]) -> float:
    pace = metric.get("classe_ritmo", "")
    intensity = metric.get("classe_intensidade", "")
    pauses = metric.get("classe_pausas", "")
    duration = metric.get("classe_duracao", "")
    score = 0.0
    if style in {"alerta_tenso", "combate_agressivo"}:
        score += {"alta": 1.5, "media": 0.5, "baixa": -0.8}.get(intensity, 0.0)
        score += {"rapido": 1.2, "normal": 0.2, "lento": -0.6}.get(pace, 0.0)
        score += 0.5 if pauses == "sem_pausa" else 0.0
    elif style == "confronto_firme":
        score += {"alta": 1.0, "media": 0.5, "baixa": -0.2}.get(intensity, 0.0)
        score += {"rapido": 0.7, "normal": 0.3, "lento": 0.0}.get(pace, 0.0)
    elif style == "investigacao_observacional":
        score += {"baixa": 0.8, "media": 0.6, "alta": 0.2}.get(intensity, 0.0)
        score += {"lento": 0.8, "normal": 0.6, "rapido": 0.0}.get(pace, 0.0)
        score += {"pausa_frequente": 1.0, "pausa_leve": 0.4, "sem_pausa": 0.0}.get(pauses, 0.0)
    elif style == "tristeza_contida":
        score += {"baixa": 1.4, "media": 0.5, "alta": -0.8}.get(intensity, 0.0)
        score += {"lento": 1.0, "normal": 0.4, "rapido": -0.7}.get(pace, 0.0)
        score += 0.8 if pauses == "pausa_frequente" else 0.2 if pauses == "pausa_leve" else 0.0
    elif style == "ironia_seca":
        score += {"lento": 0.8, "normal": 0.6, "rapido": 0.0}.get(pace, 0.0)
        score += 0.6 if pauses != "sem_pausa" else 0.0
        score += 0.3 if intensity in {"baixa", "media"} else 0.0
    elif style == "pergunta_cautelosa":
        score += {"baixa": 1.0, "media": 0.7, "alta": 0.0}.get(intensity, 0.0)
        score += {"lento": 0.8, "normal": 0.6, "rapido": 0.0}.get(pace, 0.0)
        score += 0.4 if pauses != "sem_pausa" else 0.0
    elif style == "narrativa_contida":
        score += 1.3 if duration == "longa" else 0.0
        score += {"lento": 0.6, "normal": 0.7, "rapido": 0.0}.get(pace, 0.0)
        score += 0.6 if pauses == "pausa_frequente" else 0.2 if pauses == "pausa_leve" else 0.0
    elif style == "conversa_neutra":
        score += 0.5 if pace == "normal" else 0.2
        score += 0.4 if intensity == "media" else 0.1
    return score


def choose_style(row: dict[str, str], metric: dict[str, str]) -> tuple[str, str, str, str]:
    current = row["estilo"]
    second = row["segunda_opcao"]
    scores = parse_scores(row["pontuacoes"])
    pair = {current, second}
    markers = set((row.get("marcadores") or "").split("|"))
    intensity = metric.get("classe_intensidade", "")
    pace = metric.get("classe_ritmo", "")
    pauses = metric.get("classe_pausas", "")

    if pair == {"alerta_tenso", "pergunta_cautelosa"}:
        tense = intensity == "alta" and (pace == "rapido" or pauses == "sem_pausa")
        if "exclamacao" in markers or tense:
            return "alerta_tenso", "pergunta_cautelosa", "media", "pergunta curta com ataque acústico alto/rápido"
        return "pergunta_cautelosa", "alerta_tenso", "media", "pergunta curta com prosódia cautelosa"

    if "pergunta_cautelosa" in pair:
        other = second if current == "pergunta_cautelosa" else current
        other_score = scores.get(other, 0.0)
        if other in {"investigacao_observacional", "ironia_seca", "narrativa_contida"} and other_score >= 2.4:
            return other, "pergunta_cautelosa", "media", f"semântica de {other} preservada; áudio usado como confirmação"
        if other == "confronto_firme":
            if other_score >= 3.2 or intensity == "alta" or pace == "rapido":
                return other, "pergunta_cautelosa", "media", "cobrança sustentada pela prosódia oficial"
            return "pergunta_cautelosa", other, "media", "interrogação sem energia suficiente para confronto"
        if other == "tristeza_contida" and other_score >= 3.5:
            return other, "pergunta_cautelosa", "media", "conteúdo emocional explícito preservado"
        if other == "combate_agressivo" and other_score >= 3.5 and (intensity == "alta" or pace == "rapido"):
            return other, "pergunta_cautelosa", "media", "conteúdo de combate com energia oficial compatível"
        return "pergunta_cautelosa", other, "media", "pergunta mantida após leitura da prosódia oficial"

    current_adjusted = scores.get(current, 0.0) + acoustic_support(current, metric)
    second_adjusted = scores.get(second, 0.0) + acoustic_support(second, metric)
    if second_adjusted > current_adjusted + 0.6:
        chosen, runner_up = second, current
        reason = f"segunda opção favorecida pela prosódia oficial ({second_adjusted:.2f} vs {current_adjusted:.2f})"
    else:
        chosen, runner_up = current, second
        reason = f"estilo semântico confirmado pela prosódia oficial ({current_adjusted:.2f} vs {second_adjusted:.2f})"
    margin = abs(current_adjusted - second_adjusted)
    confidence = "media" if margin >= 0.45 else "baixa"
    return chosen, runner_up, confidence, reason


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assignments-output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--changes-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        fields, rows = read_csv(args.classification)
        metrics = by_id(args.metrics)
        expected = {row["id_hex"] for row in rows if row.get("revisar") == "sim"}
        if set(metrics) != expected:
            missing = expected - set(metrics)
            extra = set(metrics) - expected
            raise RefinementError(f"cobertura acústica divergente: ausentes={len(missing)}, extras={len(extra)}")

        acoustic_fields = [
            "ritmo_oficial", "intensidade_oficial", "pausas_oficiais",
            "perfil_acustico_oficial", "estilo_antes_acustica", "motivo_refinamento",
        ]
        output_fields = fields + [field for field in acoustic_fields if field not in fields]
        changes: list[dict[str, str]] = []
        remaining: list[dict[str, str]] = []
        for row in rows:
            ident = row["id_hex"]
            metric = metrics.get(ident)
            if metric is None:
                for field in acoustic_fields:
                    row.setdefault(field, "")
                continue
            old_style = row["estilo"]
            style, second, confidence, reason = choose_style(row, metric)
            row["estilo_antes_acustica"] = old_style
            row["estilo"] = style
            row["segunda_opcao"] = second
            row["confianca"] = confidence
            row["origem_classificacao"] = "regras_semanticas+audio_oficial"
            row["ritmo_oficial"] = metric.get("classe_ritmo", "")
            row["intensidade_oficial"] = metric.get("classe_intensidade", "")
            row["pausas_oficiais"] = metric.get("classe_pausas", "")
            row["perfil_acustico_oficial"] = metric.get("perfil_acustico_id", "")
            row["motivo_refinamento"] = reason
            row["revisar"] = "não"
            row["prioridade_revisao"] = "nenhuma"

            scores = parse_scores(row["pontuacoes"])
            unresolved = confidence == "baixa" and abs(scores.get(old_style, 0.0) - scores.get(second, 0.0)) < 0.2
            if unresolved:
                row["revisar"] = "sim"
                row["prioridade_revisao"] = "media"
                remaining.append(row)
            if style != old_style:
                changes.append({
                    "id_hex": ident,
                    "texto": row["texto"],
                    "estilo_anterior": old_style,
                    "estilo_final": style,
                    "segunda_opcao": second,
                    "ritmo_oficial": row["ritmo_oficial"],
                    "intensidade_oficial": row["intensidade_oficial"],
                    "pausas_oficiais": row["pausas_oficiais"],
                    "motivo_refinamento": reason,
                })

        write_csv(args.output, output_fields, rows)
        args.assignments_output.parent.mkdir(parents=True, exist_ok=True)
        with args.assignments_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "estilo"])
            writer.writerows((row["id_hex"], row["estilo"]) for row in rows)
        write_csv(args.review_output, output_fields, remaining)
        write_csv(
            args.changes_output,
            ["id_hex", "texto", "estilo_anterior", "estilo_final", "segunda_opcao", "ritmo_oficial", "intensidade_oficial", "pausas_oficiais", "motivo_refinamento"],
            changes,
        )

        counts = Counter(row["estilo"] for row in rows)
        print(f"Classificadas: {len(rows)}; refinadas com áudio oficial: {len(metrics)}")
        print(f"Estilo alterado pela acústica: {len(changes)}; revisão restante: {len(remaining)}")
        print("Estilos finais: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
        print(f"Classificação final: {args.output}")
        print(f"Atribuições finais: {args.assignments_output}")
        print(f"Revisão restante: {args.review_output}")
        print(f"Alterações acústicas: {args.changes_output}")
        return 0
    except (OSError, RefinementError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
