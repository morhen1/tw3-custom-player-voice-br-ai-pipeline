#!/usr/bin/env python3
"""Executa um JSONL do OmniVoice em lotes retomáveis e valida cada WAV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    ident: str
    payload: dict[str, object]


def read_items(path: Path) -> list[Item]:
    result: list[Item] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RunnerError(f"JSON inválido na linha {line_number}: {exc}") from exc
            ident = str(payload.get("id", "")).strip()
            if not re_full_hex(ident):
                raise RunnerError(f"linha {line_number}: id deve ser 0x12345678")
            ident = ident.lower()
            payload["id"] = ident
            if ident in seen:
                raise RunnerError(f"ID repetido no JSONL: {ident}")
            if not str(payload.get("text", "")).strip():
                raise RunnerError(f"{ident}: texto vazio")
            seen.add(ident)
            result.append(Item(ident, payload))
    if not result:
        raise RunnerError("JSONL não contém falas")
    return result


def re_full_hex(value: str) -> bool:
    if len(value) != 10 or not value.lower().startswith("0x"):
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


def wav_info(path: Path) -> tuple[float, int, int]:
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            channels = audio.getnchannels()
    except (wave.Error, OSError) as exc:
        raise RunnerError(f"WAV ilegível: {exc}") from exc
    if frames <= 0 or rate <= 0 or channels not in {1, 2}:
        raise RunnerError("WAV vazio ou com metadados inválidos")
    return frames / rate, channels, rate


def normalize_wav_duration(
    path: Path,
    target_duration: float,
    max_trim_seconds: float,
    max_pad_seconds: float,
) -> tuple[bool, str]:
    """Remove o padding simétrico do OmniVoice ou completa poucos frames.

    Com ``postprocess_output=False``, o OmniVoice preserva o padding configurado
    ao redor da fala (normalmente 0,1 s por lado). A duração solicitada controla
    a região gerada, enquanto o WAV salvo pode ficar cerca de 0,2 s maior. Este
    ajuste remove somente essa margem. Uma saída muito curta não é mascarada:
    apenas diferenças pequenas, compatíveis com arredondamento de frames, podem
    receber silêncio.
    """
    try:
        with wave.open(str(path), "rb") as source:
            params = source.getparams()
            frame_count = source.getnframes()
            rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frames = source.readframes(frame_count)
    except (wave.Error, OSError) as exc:
        return False, f"não foi possível normalizar: {exc}"

    if rate <= 0 or channels not in {1, 2} or sample_width <= 0:
        return False, "não foi possível normalizar: metadados WAV inválidos"
    target_frames = max(1, round(target_duration * rate))
    delta_frames = frame_count - target_frames
    if delta_frames == 0:
        return True, "duração já exata"

    delta_seconds = delta_frames / rate
    bytes_per_frame = channels * sample_width
    if delta_frames > 0:
        if delta_seconds > max_trim_seconds:
            return False, f"excesso de {delta_seconds:.3f}s excede ajuste seguro"
        left = delta_frames // 2
        start = left * bytes_per_frame
        end = start + target_frames * bytes_per_frame
        adjusted = frames[start:end]
        operation = f"padding removido {delta_seconds:.3f}s"
    else:
        missing_frames = -delta_frames
        missing_seconds = missing_frames / rate
        if missing_seconds > max_pad_seconds:
            return False, f"falta de {missing_seconds:.3f}s excede ajuste seguro"
        left = missing_frames // 2
        right = missing_frames - left
        # WAV PCM de 8 bits usa 128 como silêncio; demais formatos PCM usam zero.
        silence_byte = b"\x80" if sample_width == 1 else b"\x00"
        adjusted = (
            silence_byte * (left * bytes_per_frame)
            + frames
            + silence_byte * (right * bytes_per_frame)
        )
        operation = f"silêncio completado {missing_seconds:.3f}s"

    temporary = path.with_name(path.name + ".duration_tmp")
    try:
        with wave.open(str(temporary), "wb") as destination:
            destination.setparams(params)
            destination.writeframes(adjusted)
        os.replace(temporary, path)
    except (wave.Error, OSError) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False, f"não foi possível salvar duração normalizada: {exc}"
    return True, operation


def validate_wav(
    path: Path,
    item: Item,
    tolerance_pct: float,
    normalize_duration: bool = True,
    max_trim_seconds: float = 0.30,
    max_pad_seconds: float = 0.08,
) -> tuple[bool, str]:
    if not path.is_file():
        return False, "ausente"
    try:
        duration, channels, rate = wav_info(path)
    except RunnerError as exc:
        return False, str(exc)
    target = item.payload.get("duration")
    if isinstance(target, (int, float)) and target > 0:
        adjustment = ""
        if normalize_duration and abs(duration - float(target)) > (1.0 / rate):
            normalized, adjustment = normalize_wav_duration(
                path,
                float(target),
                max_trim_seconds=max_trim_seconds,
                max_pad_seconds=max_pad_seconds,
            )
            if normalized:
                try:
                    duration, channels, rate = wav_info(path)
                except RunnerError as exc:
                    return False, str(exc)
        delta = (duration / float(target) - 1.0) * 100.0
        if abs(delta) > tolerance_pct:
            suffix = f"; {adjustment}" if adjustment else ""
            return False, (
                f"duração {duration:.3f}s vs {target:.3f}s ({delta:+.1f}%){suffix}"
            )
        detail = f"{duration:.3f}s ({delta:+.1f}%), {channels}ch/{rate}Hz"
        if adjustment:
            detail += f", {adjustment}"
    else:
        detail = f"{duration:.3f}s, {channels}ch/{rate}Hz, sem alvo"
    return True, detail


def chunks(items: list[Item], size: int) -> list[list[Item]]:
    return [items[start:start + size] for start in range(0, len(items), size)]


def cli_help(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--help"], text=True, capture_output=True, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError(f"não foi possível executar {executable}: {exc}") from exc
    return (result.stdout or "") + "\n" + (result.stderr or "")


def write_batch(path: Path, batch: list[Item]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in batch:
            handle.write(json.dumps(item.payload, ensure_ascii=False) + "\n")


def write_report(path: Path, rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["id_hex", "status", "detalhe"])
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--executable", default="omnivoice-infer-batch")
    parser.add_argument("--model", default="k2-fsa/OmniVoice")
    parser.add_argument("--items-per-batch", type=int, default=250)
    parser.add_argument("--num-step", type=int, default=32)
    parser.add_argument("--guidance-scale", type=float, default=1.8)
    parser.add_argument(
        "--preprocess-prompt",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="remove silêncios longos da referência antes de tokenizar (padrão: true)",
    )
    parser.add_argument("--nj-per-gpu", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--duration-tolerance-pct", type=float, default=8.0)
    parser.add_argument(
        "--max-padding-trim-seconds",
        type=float,
        default=0.30,
        help="máximo de padding simétrico removível do WAV (padrão: 0.30)",
    )
    parser.add_argument(
        "--max-padding-add-seconds",
        type=float,
        default=0.08,
        help="máximo de silêncio adicionável por arredondamento (padrão: 0.08)",
    )
    parser.add_argument(
        "--no-normalize-duration",
        action="store_true",
        help="desativa o ajuste do padding para a duração exata",
    )
    parser.add_argument(
        "--allow-duration-input",
        action="store_true",
        help="aceita JSONL legado com duration (pode truncar palavras)",
    )
    parser.add_argument("--check-only", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.jsonl.is_file():
            raise RunnerError(f"JSONL não encontrado: {args.jsonl}")
        if args.items_per_batch < 1 or args.batch_size < 1 or args.nj_per_gpu < 1:
            raise RunnerError("tamanhos de lote devem ser positivos")
        if not 0 < args.duration_tolerance_pct <= 100:
            raise RunnerError("tolerância de duração deve estar entre 0 e 100")
        if args.max_padding_trim_seconds < 0 or args.max_padding_add_seconds < 0:
            raise RunnerError("limites de ajuste de padding não podem ser negativos")
        items = read_items(args.jsonl)
        duration_items = [item for item in items if "duration" in item.payload]
        if duration_items and not args.allow_duration_input:
            preview = ", ".join(item.ident for item in duration_items[:5])
            raise RunnerError(
                f"JSONL contém duration em {len(duration_items)} fala(s), incluindo {preview}; "
                "gere novamente sem duração ou use --allow-duration-input somente no modo legado"
            )
        output = args.output.resolve()
        work = (args.work_dir or output / "_omnivoice_work").resolve()
        output.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        report = output / "relatorio_omnivoice.csv"

        valid: dict[str, str] = {}
        pending: list[Item] = []
        for item in items:
            ok, detail = validate_wav(
                output / f"{item.ident}.wav",
                item,
                args.duration_tolerance_pct,
                normalize_duration=not args.no_normalize_duration,
                max_trim_seconds=args.max_padding_trim_seconds,
                max_pad_seconds=args.max_padding_add_seconds,
            )
            if ok:
                valid[item.ident] = detail
            else:
                pending.append(item)
        print(f"Falas: {len(items)}; WAVs válidos: {len(valid)}; pendentes: {len(pending)}")
        if args.check_only:
            rows = [[item.ident, "valido", valid[item.ident]] for item in items if item.ident in valid]
            rows += [[item.ident, "pendente", "ausente ou inválido"] for item in pending]
            write_report(report, rows)
            print(f"Auditoria: {report}")
            return 0 if not pending else 2
        if not pending:
            print("Todos os WAVs já estão válidos.")
            return 0

        help_text = cli_help(args.executable)
        required_options = ["--model", "--test_list", "--res_dir"]
        missing_options = [option for option in required_options if option not in help_text]
        if missing_options:
            raise RunnerError(
                "CLI OmniVoice incompatível; opções ausentes: " + ", ".join(missing_options)
            )
        exact_duration_args: list[str] = []
        if "--no-postprocess_output" in help_text:
            exact_duration_args = ["--no-postprocess_output"]
        elif "--postprocess_output" in help_text:
            exact_duration_args = ["--postprocess_output", "False"]
        else:
            print("AVISO: esta versão não expõe postprocess_output; a duração será validada depois.")

        batches = chunks(pending, args.items_per_batch)
        for index, batch in enumerate(batches, start=1):
            batch_file = work / f"lote_{index:04d}.jsonl"
            write_batch(batch_file, batch)
            command = [
                args.executable,
                "--model", args.model,
                "--test_list", str(batch_file),
                "--res_dir", str(output),
                "--nj_per_gpu", str(args.nj_per_gpu),
                "--batch_size", str(args.batch_size),
                "--num_step", str(args.num_step),
            ]
            if "--guidance_scale" in help_text:
                command += ["--guidance_scale", str(args.guidance_scale)]
            if "--preprocess_prompt" in help_text:
                command += [
                    "--preprocess_prompt",
                    "True" if args.preprocess_prompt else "False",
                ]
            command += exact_duration_args
            print(f"Lote {index}/{len(batches)}: {len(batch)} fala(s)", flush=True)
            result = subprocess.run(command)
            if result.returncode:
                raise RunnerError(
                    f"OmniVoice encerrou com código {result.returncode}; lote preservado em {batch_file}"
                )
            failures: list[str] = []
            for item in batch:
                ok, detail = validate_wav(
                    output / f"{item.ident}.wav",
                    item,
                    args.duration_tolerance_pct,
                    normalize_duration=not args.no_normalize_duration,
                    max_trim_seconds=args.max_padding_trim_seconds,
                    max_pad_seconds=args.max_padding_add_seconds,
                )
                if ok:
                    valid[item.ident] = detail
                else:
                    failures.append(f"{item.ident}: {detail}")
            if failures:
                preview = "; ".join(failures[:10])
                raise RunnerError(f"{len(failures)} saída(s) inválida(s) no lote: {preview}")

        rows = [[item.ident, "valido", valid[item.ident]] for item in items]
        write_report(report, rows)
        print(f"Concluído: {len(valid)}/{len(items)} WAVs validados; relatório: {report}")
        return 0
    except (RunnerError, OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
