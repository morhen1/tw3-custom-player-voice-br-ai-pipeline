#!/usr/bin/env python3
"""Prepara dados, propostas de Geralda e amostras para revisão de pronúncia."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


GERALT_RE = re.compile(r"\bGeralt\b", re.IGNORECASE)

SPECIAL_GERALDA = {
    "0x00055e8d": "Geralda de Rívia. Bruxa em tempo integral.",
    "0x000630c1": "Geralda, de Rívia. Os bundas moles me chamam de Carniceira de Blaviken.",
    "0x00077367": "Nesse caso, diga a ele que tem outra na porta. Geralda de Rívia. E não vou embora até falar com ele.",
    # A piada depende da forma errada do nome e deve ser decidida pelo usuário.
    "0x0007a5fc": "Não é Geraldi. É Geralda.",
    "0x0007af94": "Saudações da Geralda ao Mestre Claytop.",
    "0x0007eee2": "Geralda de Rívia, bruxa.",
    "0x00087173": "Muito, quando eu ainda queria ser chamada de Geralda Roger Eric du Haute-Bellegarcie.",
    "0x0008fc4e": "Geralda de Rívia. Bruxa.",
    "0x00090a92": "Geralda de Rívia. Bruxa.",
    "0x00091335": "Geralda de Rívia. Bruxa.",
    "0x000ff100": "Geralda de Rívia. Bruxa.",
    "0x00103e25": "Bruxa Geralda.",
    "0x0010b2a6": "Geralda de Rívia. Bruxa.",
    "0x0010c1d1": "Geralda de Rívia. Bruxa. Você é Eveline Gallo? A \"Doninha\"?",
    "0x0010c939": "Geralda não vai se importar, ela adora cartas!",
    "0x0010dd8e": "Exato... Geralda era uma chata horrível antes, mas hoje tudo muda.",
    "0x0011953a": "Uma bruxa. O nome é Geralda. Então, o povo ri de você porque...?",
    "0x0011dc4f": "\"Minha querida Geralda...\"",
}

SPECIAL_REASON = {
    "0x00055e8d": "bruxo→bruxa",
    "0x000630c1": "título feminino e artigo removido para fluidez",
    "0x00077367": "outro→outra",
    "0x0007a5fc": "piada de pronúncia; exige decisão criativa",
    "0x0007af94": "do→da",
    "0x0007eee2": "bruxo→bruxa",
    "0x00087173": "chamado→chamada",
    "0x0008fc4e": "bruxo→bruxa",
    "0x00090a92": "bruxo→bruxa",
    "0x00091335": "bruxo→bruxa",
    "0x000ff100": "bruxo→bruxa",
    "0x00103e25": "bruxo→bruxa",
    "0x0010b2a6": "bruxo→bruxa",
    "0x0010c1d1": "bruxo→bruxa",
    "0x0010c939": "ele→ela",
    "0x0010dd8e": "um chato→uma chata",
    "0x0011953a": "um bruxo→uma bruxa",
    "0x0011dc4f": "meu querido→minha querida",
}

PLACES = {
    "ard skellig", "beauclair", "belgaard", "bosque da podridão", "dun tynne",
    "faroe", "fyresdal", "kaer morhen", "kaer trolde", "kovir", "loc muinne",
    "mahakam", "nilfgaard", "novigrad", "ofier", "oxenfurt", "redânia", "rívia",
    "skellige", "spikeroog", "teméria", "toussaint", "undvik", "velen", "vizíma",
    "zerrikânia",
}
GROUPS = {
    "aen elle", "caçada selvagem", "moires", "moiras", "scoia'tael", "trovadores",
    "vildkaarls",
}
TERMS = {
    "aard", "axii", "gwent", "igni", "quen", "yrden", "carpeado",
}
PHONETIC_RISK = {
    "an craite", "ard skellig", "avallac'h", "beauclair", "cerys", "dettlaff",
    "dijkstra", "emhyr", "eredin", "gaunter o'dim", "guillaume", "hjalmar",
    "imlerith", "kaer morhen", "kaer trolde", "morkvarg", "nilfgaard",
    "olgierd", "skellige", "syanna", "toussaint", "udalryk", "vizíma",
    "vlodimir von everec", "yen", "yennefer",
}


def classify(term: str) -> str:
    key = term.casefold()
    if key in PLACES:
        return "lugar/região"
    if key in GROUPS:
        return "grupo/facção"
    if key in TERMS:
        return "termo do jogo"
    return "pessoa/nome próprio"


def priority(term: str, count: int) -> str:
    if term.casefold() in PHONETIC_RISK:
        return "alta"
    if count >= 20:
        return "alta"
    if count >= 5:
        return "média"
    if count >= 2:
        return "baixa"
    return "rara"


def boundary_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\wÀ-ÖØ-öø-ÿ]){re.escape(term)}(?![\wÀ-ÖØ-öø-ÿ])", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    payloads: list[dict[str, object]] = []
    by_id: dict[str, dict[str, object]] = {}
    with args.jsonl.open("r", encoding="utf-8-sig") as handle:
        for raw in handle:
            if raw.strip():
                payload = json.loads(raw)
                ident = str(payload["id"]).lower()
                payloads.append(payload)
                by_id[ident] = payload

    geralt_rows = []
    for row in analysis["geralt"]["registros"]:
        ident = row["id_hex"]
        text = row["texto_atual"]
        proposed = SPECIAL_GERALDA.get(ident, GERALT_RE.sub("Geralda", text))
        geralt_rows.append({
            "id_hex": ident,
            "categoria": "contexto especial" if ident in SPECIAL_GERALDA else "troca direta",
            "texto_atual": text,
            "texto_proposto": proposed,
            "ajuste_adicional": SPECIAL_REASON.get(ident, "Geralt→Geralda"),
            "decisao": "revisar" if ident in SPECIAL_GERALDA else "aplicar",
            "observacoes": "",
        })

    candidates = []
    selected_ids: dict[str, dict[str, object]] = {}
    term_to_id: dict[str, str] = {}
    for candidate in analysis["candidatos"]:
        term = candidate["termo"]
        if "geralt" in term.casefold():
            continue
        if candidate.get("razao_maiusculas_min") != 1 or not candidate.get("evidencia_interna"):
            continue
        pattern = boundary_pattern(term)
        matches = [
            payload for payload in payloads
            if pattern.search(str(payload["text"]))
        ]
        if not matches:
            continue
        example = min(matches, key=lambda payload: (len(str(payload["text"])), str(payload["id"])))
        ident = str(example["id"]).lower()
        count = int(candidate["ocorrencias_linhas"])
        has_sample = count >= 5
        if has_sample:
            selected_ids.setdefault(ident, example)
            term_to_id[term] = ident
        candidates.append({
            "termo_original": term,
            "tipo_sugerido": classify(term),
            "ocorrencias": count,
            "prioridade": priority(term, count),
            "motivo_prioridade": (
                "grafia estrangeira/apóstrofo; risco fonético"
                if term.casefold() in PHONETIC_RISK
                else "frequência no lote"
            ),
            "id_exemplo": ident,
            "texto_exemplo": str(example["text"]),
            "grafia_omnivoice": "",
            "decisao": "revisar",
            "observacoes": "",
            "tem_amostra": has_sample,
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated_samples = args.output_dir / "amostras_geradas"
    generated_samples.mkdir(exist_ok=True)
    missing_generated: list[str] = []
    for ident in selected_ids:
        source = args.generated_dir / f"{ident}.wav"
        destination = generated_samples / f"{ident}.wav"
        if source.is_file():
            shutil.copy2(source, destination)
        else:
            missing_generated.append(ident)

    selection_path = args.output_dir / "selecao_amostras_oficiais.jsonl"
    with selection_path.open("w", encoding="utf-8", newline="\n") as handle:
        for ident in sorted(selected_ids):
            handle.write(json.dumps(selected_ids[ident], ensure_ascii=False) + "\n")

    review = {
        "fonte": str(args.jsonl.resolve()),
        "total_falas": len(payloads),
        "geralda": geralt_rows,
        "nomes": candidates,
        "amostras_ids": sorted(selected_ids),
        "termo_para_id": term_to_id,
        "pasta_geradas": str(generated_samples.resolve()),
        "pasta_oficiais": str((args.output_dir / "amostras_oficiais_wav").resolve()),
        "faltantes_geradas": missing_generated,
    }
    (args.output_dir / "dados_revisao.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Correções de Geralda ficam em estágio; o arquivo ativo não é alterado.
    staged = args.output_dir / "correcoes_geralda_propostas.csv"
    with staged.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write("id_hex;acao;texto;motivo\n")
        for row in geralt_rows:
            text = row["texto_proposto"].replace('"', '""')
            reason = f"Nome da protagonista: {row['ajuste_adicional']}".replace('"', '""')
            handle.write(f'{row["id_hex"]};gerar;"{text}";"{reason}"\n')

    print(f"Geralda: {len(geralt_rows)} falas propostas")
    print(f"Nomes próprios: {len(candidates)} candidatos")
    print(f"Amostras oficiais selecionadas: {len(selected_ids)} IDs")
    print(f"WAVs gerados ausentes: {len(missing_generated)}")
    print(f"Dados: {args.output_dir / 'dados_revisao.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
