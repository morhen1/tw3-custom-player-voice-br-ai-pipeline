#!/usr/bin/env python3
"""Prepara referências candidatas por estilo a partir de WAVs já gerados."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import wave
from pathlib import Path


class CandidateError(RuntimeError):
    pass


CANDIDATES = {
    "investigacao_observacional": "0x0011f1b1",
    "pergunta_cautelosa": "0x00083750",
    "ironia_seca": "0x0010fddc",
    "narrativa_contida": "0x0011cedc",
    "conversa_neutra": "0x00125d00",
}

DIRECT_STYLES = ("alerta_tenso", "confronto_firme")


def wav_info(path: Path) -> tuple[float, int, int]:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            channels = handle.getnchannels()
    except (OSError, wave.Error) as exc:
        raise CandidateError(f"WAV inválido: {path}: {exc}") from exc
    if frames <= 0 or rate <= 0 or channels not in {1, 2}:
        raise CandidateError(f"WAV sem áudio válido: {path}")
    return frames / rate, channels, rate


def read_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise CandidateError(f"CSV não encontrado: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "texto_atual", "estilo_id"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise CandidateError("CSV deve conter id_hex;texto_atual;estilo_id")
        result = {(row.get("id_hex") or "").lower(): row for row in reader}
    if not result:
        raise CandidateError("CSV vazio")
    return result


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_config(candidate_dir_in_project: str) -> str:
    lines = ["[estilos]", 'padrao = "conversa_neutra"', ""]
    for style in DIRECT_STYLES:
        lines.extend(
            [
                f"[referencias.{style}]",
                "enabled = true",
                'ref_audio = "private/referencias/referencia_base.wav"',
                'ref_text_file = "private/referencias/referencia_base.txt"',
                'prompt = "private/referencias/referencia_base.pt"',
                "preprocess_prompt = true",
                "",
            ]
        )
    base = candidate_dir_in_project.rstrip("/\\").replace("\\", "/")
    for style in CANDIDATES:
        lines.extend(
            [
                f"[referencias.{style}]",
                "enabled = true",
                f"ref_audio = {toml_string(f'{base}/{style}.wav')}",
                f"ref_text_file = {toml_string(f'{base}/{style}.txt')}",
                'prompt = ""',
                "preprocess_prompt = true",
                "",
            ]
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--generated-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument(
        "--candidate-dir-in-project",
        default="trabalho/referencias_expressivas_piloto",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        rows = read_rows(args.input)
        if not args.generated_dir.is_dir():
            raise CandidateError(f"pasta gerada não encontrada: {args.generated_dir}")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_rows: list[list[object]] = []
        for style, ident in CANDIDATES.items():
            row = rows.get(ident)
            if row is None:
                raise CandidateError(f"ID candidato ausente do CSV: {ident}")
            if row.get("estilo_id") != style:
                raise CandidateError(
                    f"{ident}: estilo esperado {style}, encontrado {row.get('estilo_id')}"
                )
            source = args.generated_dir / f"{ident}.wav"
            if not source.is_file():
                raise CandidateError(f"WAV candidato ausente: {source}")
            duration, channels, rate = wav_info(source)
            destination = args.output_dir / f"{style}.wav"
            shutil.copy2(source, destination)
            text = (row.get("texto_atual") or "").strip()
            if not text:
                raise CandidateError(f"texto vazio para {ident}")
            (args.output_dir / f"{style}.txt").write_text(
                text + "\n", encoding="utf-8"
            )
            manifest_rows.append(
                [
                    style,
                    ident,
                    text,
                    f"{duration:.6f}",
                    channels,
                    rate,
                    destination.name,
                    "candidata_nao_aprovada",
                    "áudio gerado por OmniVoice; usar apenas no teste A/B",
                ]
            )

        args.config_output.parent.mkdir(parents=True, exist_ok=True)
        args.config_output.write_text(
            build_config(args.candidate_dir_in_project), encoding="utf-8"
        )
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest_output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(
                [
                    "estilo",
                    "id_candidato",
                    "ref_text",
                    "duracao_s",
                    "canais",
                    "sample_rate_hz",
                    "arquivo",
                    "status",
                    "observacao",
                ]
            )
            writer.writerows(manifest_rows)
        print(f"Referências candidatas: {len(manifest_rows)}")
        print(f"Pasta: {args.output_dir}")
        print(f"Configuração: {args.config_output}")
        print(f"Manifesto: {args.manifest_output}")
        return 0
    except (CandidateError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
