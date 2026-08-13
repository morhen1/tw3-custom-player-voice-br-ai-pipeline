#!/usr/bin/env python3
"""Aplica decisões contextuais finais a uma classificação expressiva."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


VALID_STYLES = {
    "alerta_tenso", "combate_agressivo", "confronto_firme",
    "investigacao_observacional", "tristeza_contida", "ironia_seca",
    "pergunta_cautelosa", "narrativa_contida", "conversa_neutra",
}

REFERENCE_STATUS_BY_STYLE = {
    "combate_agressivo": "prompt_criado_teste_pendente",
    "tristeza_contida": "prompt_criado_teste_pendente",
}


class DecisionError(RuntimeError):
    pass


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        if not reader.fieldnames:
            raise DecisionError(f"CSV sem cabeçalho: {path}")
        return list(reader.fieldnames), list(reader)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classification", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assignments-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        fields, rows = read_csv(args.classification)
        _, decisions = read_csv(args.decisions)
        by_id = {row["id_hex"]: row for row in rows}
        if len(by_id) != len(rows):
            raise DecisionError("classificação contém IDs repetidos")
        report: list[list[str]] = []
        for decision in decisions:
            ident = (decision.get("id_hex") or "").strip().lower()
            style = (decision.get("estilo_final") or "").strip()
            confidence = (decision.get("confianca") or "media").strip()
            reason = (decision.get("motivo") or "").strip()
            if ident not in by_id:
                raise DecisionError(f"ID da decisão ausente: {ident}")
            if style not in VALID_STYLES:
                raise DecisionError(f"estilo inválido em {ident}: {style}")
            row = by_id[ident]
            old_style = row["estilo"]
            row["estilo"] = style
            row["confianca"] = confidence
            row["revisar"] = "não"
            row["prioridade_revisao"] = "nenhuma"
            row["origem_classificacao"] = "decisao_contextual_final"
            row["motivo_refinamento"] = reason
            report.append([ident, old_style, style, confidence, reason])

        # O refinamento acústico e as decisões manuais podem trocar o estilo.
        # Portanto, o status deve sempre refletir o estilo final, e não a
        # referência que estava associada à classificação anterior.
        for row in rows:
            row["status_referencia"] = REFERENCE_STATUS_BY_STYLE.get(
                row["estilo"], "aprovada_piloto"
            )

        extra_fields = ["ritmo_oficial", "intensidade_oficial", "pausas_oficiais", "perfil_acustico_oficial", "estilo_antes_acustica", "motivo_refinamento"]
        output_fields = fields + [field for field in extra_fields if field not in fields]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=output_fields, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        args.assignments_output.parent.mkdir(parents=True, exist_ok=True)
        with args.assignments_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "estilo"])
            writer.writerows((row["id_hex"], row["estilo"]) for row in rows)
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        with args.report_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "estilo_anterior", "estilo_final", "confianca", "motivo"])
            writer.writerows(report)
        remaining = sum(row.get("revisar") == "sim" for row in rows)
        counts = Counter(row["estilo"] for row in rows)
        print(f"Decisões aplicadas: {len(report)}; revisão restante: {remaining}")
        print("Estilos: " + ", ".join(f"{key}={counts[key]}" for key in sorted(counts)))
        print(f"Classificação aprovada: {args.output}")
        print(f"Atribuições: {args.assignments_output}")
        print(f"Relatório: {args.report_output}")
        return 0
    except (OSError, DecisionError, KeyError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
