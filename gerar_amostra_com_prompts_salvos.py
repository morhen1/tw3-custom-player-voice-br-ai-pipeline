#!/usr/bin/env python3
"""Gera uma amostra curta usando VoiceClonePrompt já salvo."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


SAMPLES = (
    (
        "combate_agressivo",
        "0x0010b1a7",
        "Estou tentando salvar suas vidas. Não encostarei em vocês, desde que não ataquem. Mas um movimento em falso e eu terei que me defender.",
    ),
    (
        "combate_agressivo",
        "0x00085826",
        "Entendi por que estava ansiosa para praticar. Ataque!",
    ),
    (
        "combate_agressivo",
        "0x001195ce",
        "Prepare-se para se defender.",
    ),
    (
        "tristeza_contida",
        "0x0010e1c9",
        "Me desculpe, Shani. Sinto muito você ter que ouvir isso...",
    ),
    (
        "tristeza_contida",
        "0x000fef07",
        "Encontrei os seus amigos. Infelizmente, estavam todos mortos. Sinto muito.",
    ),
    (
        "tristeza_contida",
        "0x00123895",
        "...infelizmente eu não consegui salvar Syanna. Dettlaff não teve misericórdia e não demonstrou nenhuma compreensão... o resto você já sabe.",
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--combat-prompt", type=Path, required=True)
    parser.add_argument("--sadness-prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--only-id")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        project_root = args.project_root.resolve()
        sys.path.insert(0, str(project_root))
        import soundfile as sf
        import torch
        from omnivoice.models.omnivoice import OmniVoice
        from voice_clone_prompt_io import load_voice_clone_prompt

        if not torch.cuda.is_available() and args.device.startswith("cuda"):
            raise RuntimeError("CUDA não está disponível")
        prompts = {
            "combate_agressivo": load_voice_clone_prompt(args.combat_prompt.resolve())[0],
            "tristeza_contida": load_voice_clone_prompt(args.sadness_prompt.resolve())[0],
        }
        args.output.mkdir(parents=True, exist_ok=True)
        selected_samples = tuple(
            sample for sample in SAMPLES if args.only_id is None or sample[1] == args.only_id
        )
        if not selected_samples:
            raise RuntimeError(f"ID não encontrado na amostra: {args.only_id}")
        if args.speed is not None and args.speed <= 0:
            raise RuntimeError("speed deve ser positivo")
        if args.duration is not None and args.duration <= 0:
            raise RuntimeError("duration deve ser positiva")
        expected = [
            args.output / f"{style}__{ident}.wav" for style, ident, _ in selected_samples
        ]
        existing = [path for path in expected if path.exists()]
        if existing and not args.force:
            raise RuntimeError(
                f"{len(existing)} saída(s) já existem; use --force para substituir"
            )

        print(f"Carregando {args.model} em {args.device} (float16)", flush=True)
        model = OmniVoice.from_pretrained(
            args.model,
            device_map=args.device,
            dtype=torch.float16,
        )
        report_rows: list[list[object]] = []
        for index, (style, ident, text) in enumerate(selected_samples, start=1):
            print(f"[{index}/{len(selected_samples)}] {style} {ident}", flush=True)
            audio = model.generate(
                text=text,
                language="pt",
                voice_clone_prompt=prompts[style],
                speed=args.speed,
                duration=args.duration,
                num_step=32,
                guidance_scale=1.8,
                preprocess_prompt=True,
                postprocess_output=False,
            )[0]
            output = args.output / f"{style}__{ident}.wav"
            sf.write(output, audio, model.sampling_rate)
            report_rows.append(
                [ident, style, text, str(output.resolve()), len(audio) / model.sampling_rate]
            )

        report = args.output / "relatorio_amostra_prompts.csv"
        with report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["id_hex", "estilo", "texto", "wav", "duracao_s"])
            writer.writerows(report_rows)
        print(f"Amostra concluída: {len(report_rows)} WAVs; relatório: {report}")
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
