#!/usr/bin/env python3
"""Cria e salva um VoiceClonePrompt reutilizável do OmniVoice."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from voice_clone_prompt_io import (
    VoicePromptError,
    load_prompt_payload,
    save_voice_clone_prompt,
    sha256_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref-audio", type=Path, required=True)
    parser.add_argument("--ref-text-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda:0, ...")
    parser.add_argument(
        "--dtype",
        choices=("auto", "float16", "float32", "bfloat16"),
        default="auto",
    )
    parser.add_argument(
        "--preprocess-prompt",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="mantém a remoção de silêncio e a pontuação automática (padrão: true)",
    )
    parser.add_argument("--force", action="store_true")
    return parser


def resolve_runtime(torch, device_arg: str, dtype_arg: str):
    if device_arg == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    else:
        device = device_arg
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise VoicePromptError("CUDA foi solicitada, mas não está disponível")
    if dtype_arg == "auto":
        dtype = torch.float16 if device.startswith("cuda") else torch.float32
    else:
        dtype = getattr(torch, dtype_arg)
    return device, dtype


def main() -> int:
    args = build_parser().parse_args()
    try:
        import torch
        from omnivoice.models.omnivoice import OmniVoice

        if not args.ref_audio.is_file():
            raise VoicePromptError(f"áudio não encontrado: {args.ref_audio}")
        if not args.ref_text_file.is_file():
            raise VoicePromptError(f"texto não encontrado: {args.ref_text_file}")
        if args.output.exists() and not args.force:
            raise VoicePromptError(f"saída já existe; use --force: {args.output}")
        ref_text = args.ref_text_file.read_text(encoding="utf-8-sig").strip()
        if not ref_text:
            raise VoicePromptError("texto de referência vazio")

        device, dtype = resolve_runtime(torch, args.device, args.dtype)
        print(f"Carregando {args.model} em {device} ({dtype})")
        model = OmniVoice.from_pretrained(
            args.model,
            device_map=device,
            dtype=dtype,
        )
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(args.ref_audio.resolve()),
            ref_text=ref_text,
            preprocess_prompt=args.preprocess_prompt,
        )
        try:
            omnivoice_version = version("omnivoice")
        except PackageNotFoundError:
            omnivoice_version = "desconhecida"
        metadata = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": args.model,
            "omnivoice_version": omnivoice_version,
            "source_audio_name": args.ref_audio.name,
            "source_audio_sha256": sha256_file(args.ref_audio),
            "source_text_name": args.ref_text_file.name,
        }
        payload = save_voice_clone_prompt(
            prompt,
            args.output,
            preprocess_prompt=args.preprocess_prompt,
            metadata=metadata,
        )
        verified = load_prompt_payload(args.output)
        if verified["ref_text"] != payload["ref_text"]:
            raise VoicePromptError("a verificação do texto salvo falhou")
        print(f"Prompt: {args.output.resolve()}")
        print(f"preprocess_prompt={verified['preprocess_prompt']}")
        print(f"Tokens: {tuple(verified['ref_audio_tokens'].shape)}")
        print(f"RMS: {float(verified['ref_rms']):.6f}")
        print(f"SHA256 do áudio: {metadata['source_audio_sha256']}")
        return 0
    except (VoicePromptError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
