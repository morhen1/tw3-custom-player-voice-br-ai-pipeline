#!/usr/bin/env python3
"""Persistência estável de VoiceClonePrompt para o OmniVoice 0.2.x."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any


PROMPT_FORMAT = "tw3-custom-player-voice-br/omnivoice-voice-clone-prompt"
PROMPT_FORMAT_VERSION = 1


class VoicePromptError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def build_prompt_payload(
    prompt: Any,
    *,
    preprocess_prompt: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        tokens = prompt.ref_audio_tokens.detach().cpu().contiguous()
        ref_text = str(prompt.ref_text).strip()
        ref_rms = float(prompt.ref_rms)
    except (AttributeError, TypeError, ValueError) as exc:
        raise VoicePromptError("objeto VoiceClonePrompt inválido") from exc
    if tokens.ndim != 2 or tokens.numel() == 0:
        raise VoicePromptError("tokens do prompt devem ter formato (C, T) e não ser vazios")
    if not ref_text:
        raise VoicePromptError("texto do prompt está vazio")
    if ref_rms < 0:
        raise VoicePromptError("RMS do prompt não pode ser negativo")
    return {
        "format": PROMPT_FORMAT,
        "format_version": PROMPT_FORMAT_VERSION,
        "preprocess_prompt": bool(preprocess_prompt),
        "ref_audio_tokens": tokens,
        "ref_text": ref_text,
        "ref_rms": ref_rms,
        "metadata": dict(metadata or {}),
    }


def validate_prompt_payload(payload: Any) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:
        raise VoicePromptError("PyTorch não está instalado") from exc
    if not isinstance(payload, dict):
        raise VoicePromptError("arquivo de prompt não contém um dicionário")
    if payload.get("format") != PROMPT_FORMAT:
        raise VoicePromptError("formato de prompt desconhecido")
    if payload.get("format_version") != PROMPT_FORMAT_VERSION:
        raise VoicePromptError("versão de formato de prompt incompatível")
    tokens = payload.get("ref_audio_tokens")
    if not isinstance(tokens, torch.Tensor) or tokens.ndim != 2 or tokens.numel() == 0:
        raise VoicePromptError("tokens ausentes ou inválidos no prompt")
    if not str(payload.get("ref_text", "")).strip():
        raise VoicePromptError("texto ausente no prompt")
    try:
        ref_rms = float(payload.get("ref_rms"))
    except (TypeError, ValueError) as exc:
        raise VoicePromptError("RMS inválido no prompt") from exc
    if ref_rms < 0:
        raise VoicePromptError("RMS negativo no prompt")
    if not isinstance(payload.get("preprocess_prompt"), bool):
        raise VoicePromptError("preprocess_prompt ausente no prompt")
    if not isinstance(payload.get("metadata", {}), dict):
        raise VoicePromptError("metadados inválidos no prompt")
    return payload


def save_voice_clone_prompt(
    prompt: Any,
    output: Path,
    *,
    preprocess_prompt: bool,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:
        raise VoicePromptError("PyTorch não está instalado") from exc
    payload = build_prompt_payload(
        prompt,
        preprocess_prompt=preprocess_prompt,
        metadata=metadata,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        torch.save(payload, temporary)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return payload


def load_prompt_payload(path: Path, map_location: str = "cpu") -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:
        raise VoicePromptError("PyTorch não está instalado") from exc
    if not path.is_file():
        raise VoicePromptError(f"prompt não encontrado: {path}")
    try:
        payload = torch.load(path, map_location=map_location, weights_only=True)
    except TypeError:
        payload = torch.load(path, map_location=map_location)
    except Exception as exc:
        raise VoicePromptError(f"não foi possível carregar {path}: {exc}") from exc
    return validate_prompt_payload(payload)


def load_voice_clone_prompt(path: Path, map_location: str = "cpu"):
    payload = load_prompt_payload(path, map_location=map_location)
    try:
        from omnivoice.models.omnivoice import VoiceClonePrompt
    except ImportError as exc:
        raise VoicePromptError("OmniVoice não está instalado") from exc
    prompt = VoiceClonePrompt(
        ref_audio_tokens=payload["ref_audio_tokens"],
        ref_text=payload["ref_text"],
        ref_rms=float(payload["ref_rms"]),
    )
    return prompt, dict(payload.get("metadata", {}))
