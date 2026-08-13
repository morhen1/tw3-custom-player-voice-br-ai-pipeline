#!/usr/bin/env python3
"""Insere silencios em posicoes seguras de um WAV sem recodificar a fala."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--insert",
        action="append",
        required=True,
        metavar="SEGUNDOS:MILISSEGUNDOS",
        help="posicao no audio original e silencio a inserir",
    )
    args = parser.parse_args()

    audio, rate = sf.read(args.input, dtype="float32", always_2d=True)
    insertions: list[tuple[int, int]] = []
    for value in args.insert:
        position_text, duration_text = value.split(":", 1)
        position = int(round(float(position_text) * rate))
        duration = int(round(float(duration_text) / 1000.0 * rate))
        if position < 0 or position > len(audio) or duration <= 0:
            raise ValueError(f"insercao invalida: {value}")
        insertions.append((position, duration))
    insertions.sort()

    pieces: list[np.ndarray] = []
    cursor = 0
    for position, duration in insertions:
        if position < cursor:
            raise ValueError("posicoes de insercao sobrepostas")
        pieces.append(audio[cursor:position])
        pieces.append(np.zeros((duration, audio.shape[1]), dtype=np.float32))
        cursor = position
    pieces.append(audio[cursor:])
    result = np.concatenate(pieces, axis=0)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, result, rate, subtype="PCM_16")
    print(
        f"OK: {args.output.resolve()} "
        f"({len(audio)/rate:.3f}s -> {len(result)/rate:.3f}s)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
