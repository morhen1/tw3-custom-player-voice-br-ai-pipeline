#!/usr/bin/env python3
"""Consolida a validacao pYIN e prepara pastas de escuta comparativa."""

from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path


WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def category(row: dict[str, str]) -> str:
    decision = row["decisao_validacao"]
    text = row.get("texto", "")
    words = len(WORD_RE.findall(text))
    if decision == "forte_suspeita_masculina":
        return "01_forte_suspeita_masculina"
    if decision == "suspeita_moderada":
        return "02_falas_revisao_manual"
    if decision == "pitch_insuficiente" and words >= 2 and "ha, ha" not in text.lower():
        return "02_falas_revisao_manual"
    if decision in {"pitch_insuficiente", "vocalizacao_curta_inconclusiva"}:
        return "03_vocalizacoes_curtas"
    return "04_falsos_positivos_pyin"


def copy_if_present(source: str, destination: Path) -> str:
    path = Path(source)
    if not path.is_file():
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return str(destination.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    with args.validation_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))

    output_rows: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for row in rows:
        ident = row["id_hex"]
        folder_name = category(row)
        counts[folder_name] = counts.get(folder_name, 0) + 1
        copied_current = ""
        copied_pandora = ""
        copied_old = ""
        if folder_name != "04_falsos_positivos_pyin":
            folder = args.output_dir / folder_name
            copied_current = copy_if_present(row["wav_final"], folder / f"{ident}.wav")
            copied_pandora = copy_if_present(
                row["pandora_wav"],
                folder / "comparacoes" / f"{ident}__pandora_anterior.wav",
            )
            copied_old = copy_if_present(
                row["referencia_antiga_wav"],
                folder / "comparacoes" / f"{ident}__referencia_antiga.wav",
            )
        result = dict(row)
        result.update(
            {
                "pasta_revisao": folder_name,
                "wav_atual_copiado": copied_current,
                "wav_pandora_comparacao_copiado": copied_pandora,
                "wav_referencia_antiga_comparacao_copiado": copied_old,
            }
        )
        output_rows.append(result)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = list(output_rows[0]) if output_rows else []
    with args.manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(output_rows)

    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    print(f"Manifesto: {args.manifest.resolve()}")
    print(f"Pastas: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
