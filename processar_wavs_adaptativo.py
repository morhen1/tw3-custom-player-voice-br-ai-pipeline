#!/usr/bin/env python3
"""Apara, trata e ajusta WAVs do OmniVoice sem cortar palavras.

A duração original é usada somente depois da síntese. O programa preserva uma
margem curta ao redor da voz, acelera apenas quando necessário e nunca excede
o limite configurado. Como a duração oficial nem sempre representa somente a
fala audível, desvios residuais são avisos por padrão; o modo estrito continua
disponível para auditorias específicas.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
import sys
import wave
from array import array
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


class ProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManifestItem:
    ident: str
    original_duration: float


@dataclass(frozen=True)
class EdgeInfo:
    raw_duration: float
    voice_start: float
    voice_end: float
    trim_start: float
    trim_end: float

    @property
    def trimmed_duration(self) -> float:
        return self.trim_end - self.trim_start


@dataclass(frozen=True)
class DurationPlan:
    speed: float
    projected_duration: float
    projected_delta_pct: float
    status: str


@dataclass(frozen=True)
class ProcessResult:
    ident: str
    status: str
    original_duration: float
    raw_duration: float | None
    voice_start: float | None
    voice_end: float | None
    trimmed_duration: float | None
    speed: float | None
    final_duration: float | None
    delta_pct: float | None
    detail: str


def normalize_id(value: str) -> str:
    token = value.strip().lower()
    if len(token) != 10 or not token.startswith("0x"):
        raise ProcessingError(f"ID inválido: {value}")
    try:
        int(token[2:], 16)
    except ValueError as exc:
        raise ProcessingError(f"ID inválido: {value}") from exc
    return token


def read_manifest(path: Path) -> list[ManifestItem]:
    result: list[ManifestItem] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "duracao_original"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ProcessingError(
                f"{path}: manifesto deve conter id_hex;acao;duracao_original"
            )
        for line_number, row in enumerate(reader, start=2):
            if (row.get("acao") or "").strip().lower() != "gerar":
                continue
            ident = normalize_id(row.get("id_hex") or "")
            if ident in seen:
                raise ProcessingError(f"{path}: ID repetido: {ident}")
            try:
                duration = float((row.get("duracao_original") or "").replace(",", "."))
            except ValueError as exc:
                raise ProcessingError(
                    f"{path}, linha {line_number}: duração inválida"
                ) from exc
            if duration <= 0:
                raise ProcessingError(
                    f"{path}, linha {line_number}: duração deve ser positiva"
                )
            result.append(ManifestItem(ident, duration))
            seen.add(ident)
    if not result:
        raise ProcessingError(f"nenhuma fala gerável encontrada em {path}")
    return result


def read_selection_jsonl(path: Path) -> set[str]:
    result: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ProcessingError(f"{path}, linha {line_number}: JSON inválido") from exc
            result.add(normalize_id(str(payload.get("id", ""))))
    if not result:
        raise ProcessingError(f"seleção vazia: {path}")
    return result


def wav_info(path: Path) -> tuple[float, int, int, int]:
    try:
        with wave.open(str(path), "rb") as audio:
            frames = audio.getnframes()
            rate = audio.getframerate()
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            compression = audio.getcomptype()
    except (OSError, wave.Error) as exc:
        raise ProcessingError(f"WAV ilegível: {exc}") from exc
    if frames <= 0 or rate <= 0 or channels not in {1, 2} or compression != "NONE":
        raise ProcessingError("WAV vazio, comprimido ou com metadados inválidos")
    return frames / rate, channels, rate, width


def pcm16_rms_db(data: bytes) -> float:
    if not data:
        return -math.inf
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return -math.inf
    mean_square = sum(int(value) * int(value) for value in samples) / len(samples)
    if mean_square <= 0:
        return -math.inf
    return 20.0 * math.log10(math.sqrt(mean_square) / 32768.0)


def detect_voice_edges(
    path: Path,
    threshold_db: float = -45.0,
    frame_ms: float = 20.0,
    padding_ms: float = 80.0,
) -> EdgeInfo:
    """Localiza bordas sustentadas da voz em PCM16 e preserva padding seguro."""
    try:
        with wave.open(str(path), "rb") as audio:
            total_frames = audio.getnframes()
            rate = audio.getframerate()
            channels = audio.getnchannels()
            width = audio.getsampwidth()
            compression = audio.getcomptype()
            if (
                total_frames <= 0
                or rate <= 0
                or channels not in {1, 2}
                or width != 2
                or compression != "NONE"
            ):
                raise ProcessingError(
                    "detecção de bordas exige WAV PCM16 mono ou estéreo"
                )
            chunk_frames = max(1, round(rate * frame_ms / 1000.0))
            chunk_count = math.ceil(total_frames / chunk_frames)
            cache: dict[int, bool] = {}

            def active(index: int) -> bool:
                if index < 0 or index >= chunk_count:
                    return False
                if index not in cache:
                    audio.setpos(index * chunk_frames)
                    data = audio.readframes(min(chunk_frames, total_frames - index * chunk_frames))
                    cache[index] = pcm16_rms_db(data) >= threshold_db
                return cache[index]

            # Dois de três quadros ativos eliminam cliques isolados sem perder
            # consoantes suaves; o padding posterior recupera o ataque completo.
            first: int | None = None
            for index in range(chunk_count):
                if sum(active(probe) for probe in range(index, min(index + 3, chunk_count))) >= 2:
                    first = index
                    break
            last: int | None = None
            for index in range(chunk_count - 1, -1, -1):
                if sum(active(probe) for probe in range(max(0, index - 2), index + 1)) >= 2:
                    last = index
                    break
    except (OSError, wave.Error) as exc:
        raise ProcessingError(f"não foi possível analisar o WAV: {exc}") from exc

    if first is None or last is None or last < first:
        raise ProcessingError("nenhuma voz sustentada detectada")
    raw_duration = total_frames / rate
    voice_start = first * chunk_frames / rate
    voice_end = min(total_frames, (last + 1) * chunk_frames) / rate
    padding = padding_ms / 1000.0
    trim_start = max(0.0, voice_start - padding)
    trim_end = min(raw_duration, voice_end + padding)
    if trim_end <= trim_start:
        raise ProcessingError("intervalo de voz inválido")
    return EdgeInfo(raw_duration, voice_start, voice_end, trim_start, trim_end)


def plan_duration(
    original_duration: float,
    trimmed_duration: float,
    allowed_over_pct: float = 15.0,
    max_speed: float = 1.20,
    minimum_ratio: float = 0.60,
    allowed_over_seconds: float = 0.50,
) -> DurationPlan:
    speed_target = original_duration * (1.0 + allowed_over_pct / 100.0)
    allowed_duration = max(speed_target, original_duration + allowed_over_seconds)
    # Filtros como loudnorm/limiter podem acrescentar alguns milissegundos por
    # arredondamento. Reserve até 20 ms para o arquivo final não ultrapassar a
    # tolerância declarada, sem penalizar excessivamente falas muito curtas.
    processing_margin = min(0.020, original_duration * 0.02)
    # A margem absoluta existe apenas para não rejeitar interjeições aprovadas
    # auditivamente. O cálculo de velocidade continua usando a meta percentual,
    # preservando exatamente o tratamento sonoro já validado na amostra.
    planning_target = max(original_duration, speed_target - processing_margin)
    required_speed = max(1.0, trimmed_duration / planning_target)
    speed = min(required_speed, max_speed)
    projected = trimmed_duration / speed
    delta = (projected / original_duration - 1.0) * 100.0
    if projected < original_duration * minimum_ratio:
        status = "revisar_curta"
    elif projected > allowed_duration + 0.001:
        status = "revisar_longa"
    else:
        status = "ok"
    return DurationPlan(speed, projected, delta, status)


def format_number(value: float | None, digits: int = 6) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def build_filter(edges: EdgeInfo, plan: DurationPlan, target_lufs: float) -> str:
    filters = [
        f"atrim=start={edges.trim_start:.6f}:end={edges.trim_end:.6f}",
        "asetpts=PTS-STARTPTS",
    ]
    if plan.speed > 1.000001:
        filters.append(f"atempo={plan.speed:.6f}")
    filters.extend([
        "highpass=f=90",
        "equalizer=f=300:t=q:w=1:g=-4",
        "equalizer=f=3500:t=q:w=1.2:g=3",
        "acompressor=threshold=0.1:ratio=3:attack=15:release=200:makeup=1",
        f"loudnorm=I={target_lufs:g}:LRA=5:TP=-6",
        "alimiter=limit=0.5:attack=5:release=50:level=false:latency=true",
    ])
    return ",".join(filters)


def classify_final(
    original_duration: float,
    final_duration: float,
    allowed_over_pct: float,
    minimum_ratio: float,
    allowed_over_seconds: float,
    duration_audit: str = "advisory",
) -> tuple[str, float]:
    delta = (final_duration / original_duration - 1.0) * 100.0
    if final_duration < original_duration * minimum_ratio:
        prefix = "revisar" if duration_audit == "strict" else "aviso"
        return f"{prefix}_curta", delta
    allowed_duration = max(
        original_duration * (1.0 + allowed_over_pct / 100.0),
        original_duration + allowed_over_seconds,
    )
    if final_duration > allowed_duration + 0.02:
        prefix = "revisar" if duration_audit == "strict" else "aviso"
        return f"{prefix}_longa", delta
    return "ok", delta


def process_one(
    item: ManifestItem,
    input_dir: Path,
    output_dir: Path,
    ffmpeg: str,
    threshold_db: float,
    frame_ms: float,
    padding_ms: float,
    allowed_over_pct: float,
    allowed_over_seconds: float,
    max_speed: float,
    minimum_ratio: float,
    target_lufs: float,
    duration_audit: str,
    force: bool,
) -> ProcessResult:
    source = input_dir / f"{item.ident}.wav"
    destination = output_dir / f"{item.ident}.wav"
    if not source.is_file():
        return ProcessResult(
            item.ident, "falha", item.original_duration,
            None, None, None, None, None, None, None, "WAV de entrada ausente",
        )
    if destination.is_file() and not force:
        try:
            final_duration, channels, rate, width = wav_info(destination)
            if (channels, rate, width) != (1, 48000, 2):
                raise ProcessingError(
                    f"saída existente incompatível: {channels}ch/{rate}Hz/{width * 8}bit"
                )
            status, delta = classify_final(
                item.original_duration, final_duration, allowed_over_pct,
                minimum_ratio, allowed_over_seconds, duration_audit,
            )
            return ProcessResult(
                item.ident, status, item.original_duration,
                None, None, None, None, None, final_duration, delta,
                "saída existente validada; use --force para refazer",
            )
        except ProcessingError as exc:
            return ProcessResult(
                item.ident, "falha", item.original_duration,
                None, None, None, None, None, None, None, str(exc),
            )
    try:
        edges = detect_voice_edges(source, threshold_db, frame_ms, padding_ms)
        plan = plan_duration(
            item.original_duration,
            edges.trimmed_duration,
            allowed_over_pct,
            max_speed,
            minimum_ratio,
            allowed_over_seconds,
        )
        temporary = destination.with_name(destination.stem + ".tmp.wav")
        command = [
            ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-af", build_filter(edges, plan, target_lufs),
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
            str(temporary),
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode:
            raise ProcessingError(
                "FFmpeg falhou: " + (result.stderr.strip() or f"código {result.returncode}")
            )
        final_duration, channels, rate, width = wav_info(temporary)
        if (channels, rate, width) != (1, 48000, 2):
            raise ProcessingError(
                f"saída incompatível: {channels}ch/{rate}Hz/{width * 8}bit"
            )
        status, delta = classify_final(
            item.original_duration, final_duration, allowed_over_pct,
            minimum_ratio, allowed_over_seconds, duration_audit,
        )
        os.replace(temporary, destination)
        if status == "ok":
            detail = "processado"
        elif status.startswith("aviso_"):
            detail = "processado; diferença de duração registrada para referência"
        else:
            detail = "gerado, mas requer nova síntese/revisão"
        return ProcessResult(
            item.ident, status, item.original_duration,
            edges.raw_duration, edges.voice_start, edges.voice_end,
            edges.trimmed_duration, plan.speed, final_duration, delta, detail,
        )
    except (OSError, ProcessingError, ValueError) as exc:
        try:
            destination.with_name(destination.stem + ".tmp.wav").unlink(missing_ok=True)
        except OSError:
            pass
        return ProcessResult(
            item.ident, "falha", item.original_duration,
            None, None, None, None, None, None, None, str(exc),
        )


def write_report(path: Path, results: list[ProcessResult]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([
            "id_hex", "status", "duracao_original", "duracao_bruta",
            "inicio_voz", "fim_voz", "duracao_aparada", "fator_velocidade",
            "duracao_final", "delta_final_pct", "detalhe",
        ])
        for item in results:
            writer.writerow([
                item.ident,
                item.status,
                format_number(item.original_duration),
                format_number(item.raw_duration),
                format_number(item.voice_start),
                format_number(item.voice_end),
                format_number(item.trimmed_duration),
                format_number(item.speed),
                format_number(item.final_duration),
                format_number(item.delta_pct, 3),
                item.detail,
            ])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--selection-jsonl", type=Path)
    parser.add_argument("--only-id", action="append", default=[])
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--silence-threshold-db", type=float, default=-45.0)
    parser.add_argument("--frame-ms", type=float, default=20.0)
    parser.add_argument("--edge-padding-ms", type=float, default=80.0)
    parser.add_argument("--allowed-over-pct", type=float, default=15.0)
    parser.add_argument("--allowed-over-seconds", type=float, default=0.50)
    parser.add_argument("--max-speed", type=float, default=1.20)
    parser.add_argument("--minimum-ratio", type=float, default=0.60)
    parser.add_argument(
        "--duration-audit",
        choices=("advisory", "strict"),
        default="advisory",
        help=(
            "advisory registra desvios de duração sem reprovar o lote; "
            "strict exige revisão manual"
        ),
    )
    parser.add_argument("--target-lufs", type=float, default=-23.0)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.manifest.is_file():
            raise ProcessingError(f"manifesto não encontrado: {args.manifest}")
        if not args.input.is_dir():
            raise ProcessingError(f"pasta de entrada não encontrada: {args.input}")
        if args.selection_jsonl and not args.selection_jsonl.is_file():
            raise ProcessingError(f"JSONL de seleção não encontrado: {args.selection_jsonl}")
        if args.workers < 1:
            raise ProcessingError("--workers deve ser positivo")
        if not -80.0 <= args.silence_threshold_db <= -20.0:
            raise ProcessingError("--silence-threshold-db deve estar entre -80 e -20")
        if args.frame_ms <= 0 or args.edge_padding_ms < 0:
            raise ProcessingError("frame/padding inválidos")
        if not 0 <= args.allowed_over_pct <= 100:
            raise ProcessingError("--allowed-over-pct deve estar entre 0 e 100")
        if not 0 <= args.allowed_over_seconds <= 5:
            raise ProcessingError("--allowed-over-seconds deve estar entre 0 e 5")
        if not 1.0 <= args.max_speed <= 2.0:
            raise ProcessingError("--max-speed deve estar entre 1 e 2")
        if not 0 < args.minimum_ratio <= 1.0:
            raise ProcessingError("--minimum-ratio deve estar entre 0 e 1")

        ffmpeg = shutil.which(args.ffmpeg)
        if ffmpeg is None and Path(args.ffmpeg).is_file():
            ffmpeg = str(Path(args.ffmpeg).resolve())
        if ffmpeg is None:
            raise ProcessingError(f"FFmpeg não encontrado: {args.ffmpeg}")

        items = read_manifest(args.manifest)
        selected_ids: set[str] | None = None
        if args.selection_jsonl:
            selected_ids = read_selection_jsonl(args.selection_jsonl)
        if args.only_id:
            explicit = {normalize_id(value) for value in args.only_id}
            selected_ids = explicit if selected_ids is None else selected_ids & explicit
        if selected_ids is not None:
            known = {item.ident for item in items}
            missing = sorted(selected_ids - known)
            if missing:
                raise ProcessingError(
                    "IDs selecionados ausentes do manifesto: " + ", ".join(missing[:10])
                )
            items = [item for item in items if item.ident in selected_ids]
        if not items:
            raise ProcessingError("nenhuma fala selecionada")

        args.output.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        print(
            f"Falas selecionadas: {len(items)}; workers={args.workers}; "
            f"aceleração máxima={args.max_speed:.2f}x"
        )
        results_by_id: dict[str, ProcessResult] = {}
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    process_one,
                    item,
                    args.input.resolve(),
                    args.output.resolve(),
                    ffmpeg,
                    args.silence_threshold_db,
                    args.frame_ms,
                    args.edge_padding_ms,
                    args.allowed_over_pct,
                    args.allowed_over_seconds,
                    args.max_speed,
                    args.minimum_ratio,
                    args.target_lufs,
                    args.duration_audit,
                    args.force,
                ): item
                for item in items
            }
            completed = 0
            for future in as_completed(futures):
                result = future.result()
                results_by_id[result.ident] = result
                completed += 1
                if completed == 1 or completed % 25 == 0 or completed == len(items):
                    print(f"Progresso: {completed}/{len(items)}", flush=True)

        results = [results_by_id[item.ident] for item in items]
        write_report(args.report, results)
        counts: dict[str, int] = {}
        for result in results:
            counts[result.status] = counts.get(result.status, 0) + 1
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        print(f"Resultado: {summary}")
        print(f"Relatório: {args.report}")
        failures = counts.get("falha", 0)
        reviews = counts.get("revisar_curta", 0) + counts.get("revisar_longa", 0)
        warnings = counts.get("aviso_curta", 0) + counts.get("aviso_longa", 0)
        if failures:
            raise ProcessingError(f"{failures} fala(s) falharam")
        if reviews:
            raise ProcessingError(
                f"{reviews} fala(s) exigem nova geração/revisão; consulte o relatório"
            )
        if warnings:
            print(
                f"Avisos de duração: {warnings}; não bloqueiam porque a amostra "
                "auditiva foi aprovada."
            )
        print("Pós-processamento aprovado.")
        return 0
    except (ProcessingError, OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
