#!/usr/bin/env python3
"""Cria uma variante autorizada alongando apenas pausas já existentes."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


class PauseError(RuntimeError):
    pass


def find_runs(mask) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, state in enumerate(mask):
        if bool(state) and start is None:
            start = index
        elif not bool(state) and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def detect_pauses(
    audio,
    sample_rate: int,
    threshold_db: float = -35.0,
    minimum_ms: float = 100.0,
    ignore_edge_ms: float = 150.0,
) -> list[tuple[int, int]]:
    import numpy as np

    mono = np.mean(audio, axis=1) if audio.ndim == 2 else audio
    frame_length = max(1, round(sample_rate * 0.020))
    hop_length = max(1, round(sample_rate * 0.010))
    if mono.size < frame_length:
        return []
    frame_count = 1 + math.ceil((mono.size - frame_length) / hop_length)
    padded_size = (frame_count - 1) * hop_length + frame_length
    padded = np.pad(mono, (0, max(0, padded_size - mono.size)))
    rms = np.empty(frame_count, dtype=np.float64)
    for index in range(frame_count):
        frame = padded[index * hop_length : index * hop_length + frame_length]
        rms[index] = math.sqrt(float(np.mean(np.square(frame, dtype=np.float64))))
    peak = float(np.max(rms))
    if peak < 1e-9:
        return []
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-12) / peak)
    runs = find_runs(rms_db <= threshold_db)

    minimum_samples = round(sample_rate * minimum_ms / 1000.0)
    edge_samples = round(sample_rate * ignore_edge_ms / 1000.0)
    intervals: list[tuple[int, int]] = []
    for frame_start, frame_end in runs:
        start = frame_start * hop_length
        end = min(mono.size, (frame_end - 1) * hop_length + frame_length)
        if start < edge_samples or end > mono.size - edge_samples:
            continue
        if end - start >= minimum_samples:
            intervals.append((start, end))
    return intervals


def insert_silence(audio, intervals: list[tuple[int, int]], extra_samples: int):
    import numpy as np

    if extra_samples <= 0:
        raise PauseError("a duração extra deve ser positiva")
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    silence_shape = (extra_samples,) if channels == 1 else (extra_samples, channels)
    silence = np.zeros(silence_shape, dtype=audio.dtype)
    pieces = []
    cursor = 0
    for start, end in intervals:
        midpoint = (start + end) // 2
        pieces.extend((audio[cursor:midpoint], silence))
        cursor = midpoint
    pieces.append(audio[cursor:])
    return np.concatenate(pieces, axis=0)


def rewrite_jsonl(source: Path, output: Path, reference_audio: Path) -> int:
    count = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with source.open("r", encoding="utf-8-sig") as input_handle, output.open(
        "w", encoding="utf-8", newline="\n"
    ) as output_handle:
        for line_number, raw in enumerate(input_handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise PauseError(
                    f"{source}, linha {line_number}: JSON inválido"
                ) from exc
            payload["ref_audio"] = str(reference_audio.resolve())
            output_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            count += 1
    if count == 0:
        raise PauseError(f"JSONL vazio: {source}")
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--extra-ms", type=float, default=180.0)
    parser.add_argument("--threshold-db", type=float, default=-35.0)
    parser.add_argument("--minimum-pause-ms", type=float, default=100.0)
    parser.add_argument("--jsonl-input", type=Path)
    parser.add_argument("--jsonl-output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        import soundfile as sf

        if not args.input.is_file():
            raise PauseError(f"referência não encontrada: {args.input}")
        if args.output.exists() and not args.force:
            raise PauseError(f"saída já existe; use --force: {args.output}")
        if (args.jsonl_input is None) != (args.jsonl_output is None):
            raise PauseError("use --jsonl-input e --jsonl-output juntos")
        if args.jsonl_input is not None and not args.jsonl_input.is_file():
            raise PauseError(f"JSONL não encontrado: {args.jsonl_input}")
        if args.jsonl_output is not None and args.jsonl_output.exists() and not args.force:
            raise PauseError(f"JSONL de saída já existe; use --force: {args.jsonl_output}")

        audio, sample_rate = sf.read(args.input, dtype="float32", always_2d=False)
        intervals = detect_pauses(
            audio,
            sample_rate,
            threshold_db=args.threshold_db,
            minimum_ms=args.minimum_pause_ms,
        )
        if not intervals:
            raise PauseError("nenhuma pausa interna adequada foi detectada")
        extra_samples = round(sample_rate * args.extra_ms / 1000.0)
        adjusted = insert_silence(audio, intervals, extra_samples)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(args.output, adjusted, sample_rate, subtype="PCM_16")

        print(f"Pausas alongadas: {len(intervals)}")
        for number, (start, end) in enumerate(intervals, start=1):
            print(
                f"  {number}: {start / sample_rate:.3f}s–{end / sample_rate:.3f}s "
                f"(+{args.extra_ms:.0f} ms)"
            )
        print(f"Duração: {len(audio) / sample_rate:.3f}s -> {len(adjusted) / sample_rate:.3f}s")
        print(f"Referência: {args.output}")

        if args.jsonl_input is not None and args.jsonl_output is not None:
            count = rewrite_jsonl(args.jsonl_input, args.jsonl_output, args.output)
            print(f"JSONL: {args.jsonl_output} ({count} fala(s))")
        return 0
    except (PauseError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
