#!/usr/bin/env python3
"""Organiza pares de WAV e enriquece o JSON que alimenta a planilha."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from pathlib import Path


AMBIGUOUS = {
    "anna", "arminho", "carpeado", "iris", "júnior", "rosa",
}


def safe_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._'-]+", "_", ascii_name).strip("_.")
    return ascii_name[:70] or "termo"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--official-dir", type=Path, required=True)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.data.read_text(encoding="utf-8"))
    official_out = args.assets_dir / "oficial"
    generated_out = args.assets_dir / "nova_voz"
    official_out.mkdir(parents=True, exist_ok=True)
    generated_out.mkdir(parents=True, exist_ok=True)

    copied_ids: set[str] = set()
    sample_index = 0
    for row in data["nomes"]:
        term = row["termo_original"]
        ident = row["id_exemplo"]
        row["escopo_recomendado"] = (
            "frase/ID" if term.casefold() in AMBIGUOUS
            else ("frase exata" if " " in term else "termo inteiro")
        )
        row["status_revisao"] = "pendente"
        row["wav_oficial"] = ""
        row["wav_nova_voz"] = ""
        if not row["tem_amostra"]:
            continue
        source_official = args.official_dir / f"{ident}.wav"
        source_generated = args.generated_dir / f"{ident}.wav"
        if not source_official.is_file() or not source_generated.is_file():
            row["tem_amostra"] = False
            continue
        sample_index += 1
        label = f"{sample_index:03d}_{safe_name(term)}__{ident}"
        target_official = official_out / f"{label}__oficial.wav"
        target_generated = generated_out / f"{label}__nova.wav"
        shutil.copy2(source_official, target_official)
        shutil.copy2(source_generated, target_generated)
        row["wav_oficial"] = str(target_official.resolve())
        row["wav_nova_voz"] = str(target_generated.resolve())
        copied_ids.add(ident)

    data["amostras_pareadas"] = sample_index
    data["ids_pareados"] = len(copied_ids)
    data["pasta_pares"] = str(args.assets_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Pares organizados: {sample_index}")
    print(f"IDs únicos: {len(copied_ids)}")
    print(f"Dados finais: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
