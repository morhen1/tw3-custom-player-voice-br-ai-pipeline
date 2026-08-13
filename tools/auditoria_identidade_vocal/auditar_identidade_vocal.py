#!/usr/bin/env python3
"""Audita desvios de identidade vocal em um lote de WAVs.

Esta auditoria e conservadora: ela procura sobretudo geracoes com pitch
predominantemente masculino e desvios acusticos em relacao ao restante do
lote. Os resultados servem para priorizar escuta humana; nenhum audio e
alterado por este programa.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly


ID_RE = re.compile(r"^0x[0-9a-f]{8}$")
TARGET_SR = 16_000
FRAME_LENGTH = 1024
HOP_LENGTH = 160


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    ident: str
    text: str
    estilo: str
    path: Path
    fonte: str


def normalize_id(value: str) -> str:
    ident = value.strip().lower()
    if not ID_RE.fullmatch(ident):
        raise AuditError(f"ID invalido: {value!r}")
    return ident


def read_jsonl(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise AuditError(f"JSON invalido em {path}:{number}: {exc}") from exc
            ident = normalize_id(str(value.get("id", "")))
            if ident in rows:
                raise AuditError(f"ID duplicado no JSONL: {ident}")
            rows[ident] = {
                "text": str(value.get("text", "")),
                "ref_audio": str(value.get("ref_audio", "")),
            }
    return rows


def read_assignments(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, delimiter=";")
        for number, row in enumerate(rows, 1):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().lower() in {"id", "id_hex"}:
                continue
            if len(row) < 2:
                raise AuditError(f"Linha incompleta em {path}:{number}")
            ident = normalize_id(row[0])
            result[ident] = row[1].strip() or "sem_estilo"
    return result


def scan_wavs(directory: Path) -> dict[str, Path]:
    if not directory.is_dir():
        raise AuditError(f"Pasta WAV nao encontrada: {directory}")
    result: dict[str, Path] = {}
    for path in directory.glob("*.wav"):
        ident = path.stem.lower()
        if ID_RE.fullmatch(ident):
            result[ident] = path.resolve()
    return result


def build_items(
    jsonl: Path,
    assignments: Path,
    base_dir: Path,
    overlay_dirs: list[Path],
    fallback_dir: Path | None,
) -> list[Item]:
    metadata = read_jsonl(jsonl)
    styles = read_assignments(assignments)
    paths = scan_wavs(base_dir)
    sources = {ident: "base_multireferencia" for ident in paths}
    for overlay in overlay_dirs:
        for ident, path in scan_wavs(overlay).items():
            if ident in metadata:
                paths[ident] = path
                sources[ident] = f"sobreposicao:{overlay.name}"

    missing = sorted(set(metadata) - set(paths))
    if missing:
        preview = ", ".join(missing[:20])
        raise AuditError(f"{len(missing)} WAV(s) do JSONL ausentes; primeiros: {preview}")

    items = [
        Item(
            ident=ident,
            text=metadata[ident]["text"],
            estilo=styles.get(ident, "sem_estilo"),
            path=paths[ident],
            fonte=sources[ident],
        )
        for ident in sorted(metadata)
    ]

    if fallback_dir is not None:
        fallback = scan_wavs(fallback_dir)
        for ident in sorted(set(fallback) - set(metadata)):
            items.append(
                Item(
                    ident=ident,
                    text="",
                    estilo="complemento_pandora",
                    path=fallback[ident],
                    fonte=f"complemento:{fallback_dir.name}",
                )
            )
    return items


def load_audio(path: Path) -> np.ndarray:
    try:
        signal, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    except (OSError, RuntimeError) as exc:
        raise AuditError(f"Nao foi possivel ler {path}: {exc}") from exc
    if signal.ndim == 2:
        signal = signal.mean(axis=1, dtype=np.float32)
    if signal.ndim != 1 or signal.size == 0:
        raise AuditError(f"WAV vazio ou invalido: {path}")
    signal = np.nan_to_num(signal.astype(np.float32, copy=False))
    if sample_rate != TARGET_SR:
        divisor = math.gcd(int(sample_rate), TARGET_SR)
        signal = resample_poly(
            signal,
            TARGET_SR // divisor,
            int(sample_rate) // divisor,
        ).astype(np.float32, copy=False)
    signal -= float(np.mean(signal))
    peak = float(np.max(np.abs(signal)))
    if peak <= 1e-6:
        raise AuditError(f"WAV silencioso: {path}")
    signal /= peak
    trimmed, _ = librosa.effects.trim(signal, top_db=38, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)
    return trimmed if trimmed.size >= FRAME_LENGTH else signal


def percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if values.size else math.nan


def extract_features(item: Item) -> dict[str, object]:
    signal = load_audio(item.path)
    duration = signal.size / TARGET_SR
    f0 = librosa.yin(
        signal,
        fmin=65.0,
        fmax=400.0,
        sr=TARGET_SR,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        trough_threshold=0.15,
    )
    rms = librosa.feature.rms(
        y=signal,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        center=True,
    )[0]
    size = min(f0.size, rms.size)
    f0 = f0[:size]
    rms = rms[:size]
    energy_floor = max(float(np.quantile(rms, 0.20)), 10 ** (-42.0 / 20.0))
    voiced = f0[(rms >= energy_floor) & np.isfinite(f0)]
    if voiced.size < 3:
        raise AuditError(f"Pitch insuficiente: {item.path}")

    mfcc = librosa.feature.mfcc(
        y=signal,
        sr=TARGET_SR,
        n_mfcc=14,
        n_fft=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
    )
    active_frames = rms >= energy_floor
    active_frames = active_frames[: mfcc.shape[1]]
    selected_mfcc = mfcc[:, active_frames] if np.any(active_frames) else mfcc

    centroid = librosa.feature.spectral_centroid(
        y=signal,
        sr=TARGET_SR,
        n_fft=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
    )[0]
    rolloff = librosa.feature.spectral_rolloff(
        y=signal,
        sr=TARGET_SR,
        n_fft=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        roll_percent=0.90,
    )[0]
    flatness = librosa.feature.spectral_flatness(
        y=signal,
        n_fft=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
    )[0]

    result: dict[str, object] = {
        "id_hex": item.ident,
        "texto": item.text,
        "estilo": item.estilo,
        "fonte": item.fonte,
        "wav": str(item.path),
        "duracao_s": round(duration, 6),
        "quadros_pitch": int(voiced.size),
        "f0_mediana_hz": round(float(np.median(voiced)), 4),
        "f0_p10_hz": round(percentile(voiced, 10), 4),
        "f0_p90_hz": round(percentile(voiced, 90), 4),
        "f0_iqr_hz": round(percentile(voiced, 75) - percentile(voiced, 25), 4),
        "fracao_abaixo_140": round(float(np.mean(voiced < 140.0)), 6),
        "fracao_abaixo_150": round(float(np.mean(voiced < 150.0)), 6),
        "fracao_abaixo_160": round(float(np.mean(voiced < 160.0)), 6),
        "fracao_abaixo_170": round(float(np.mean(voiced < 170.0)), 6),
        "fracao_abaixo_180": round(float(np.mean(voiced < 180.0)), 6),
        "centroide_hz": round(float(np.median(centroid)), 4),
        "rolloff90_hz": round(float(np.median(rolloff)), 4),
        "flatness_mediana": round(float(np.median(flatness)), 8),
    }
    for index in range(1, selected_mfcc.shape[0]):
        result[f"mfcc{index:02d}_media"] = round(float(np.mean(selected_mfcc[index])), 6)
        result[f"mfcc{index:02d}_desvio"] = round(float(np.std(selected_mfcc[index])), 6)
    return result


def robust_style_stats(rows: list[dict[str, object]]) -> dict[str, tuple[float, float]]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        if row.get("erro"):
            continue
        grouped.setdefault(str(row["estilo"]), []).append(float(row["f0_mediana_hz"]))
    result: dict[str, tuple[float, float]] = {}
    for style, values in grouped.items():
        array = np.asarray(values, dtype=np.float64)
        median = float(np.median(array))
        mad = float(np.median(np.abs(array - median)))
        result[style] = (median, max(1.4826 * mad, 5.0))
    return result


def classify(rows: list[dict[str, object]], known_male: set[str]) -> None:
    stats = robust_style_stats(rows)
    for row in rows:
        ident = str(row["id_hex"])
        if row.get("erro"):
            row.update(
                {
                    "z_pitch_estilo": "",
                    "risco_identidade": 100,
                    "prioridade_identidade": "alta",
                    "motivos_identidade": "erro ao analisar o WAV",
                }
            )
            continue
        f0 = float(row["f0_mediana_hz"])
        under150 = float(row["fracao_abaixo_150"])
        under160 = float(row["fracao_abaixo_160"])
        under170 = float(row["fracao_abaixo_170"])
        under180 = float(row["fracao_abaixo_180"])
        style_median, style_scale = stats[str(row["estilo"])]
        z_style = (f0 - style_median) / style_scale

        score = 0.0
        score += np.clip((185.0 - f0) / 45.0, 0.0, 1.0) * 45.0
        score += under160 * 30.0
        score += under170 * 15.0
        score += np.clip((-z_style - 1.5) / 3.0, 0.0, 1.0) * 10.0
        score = float(np.clip(score, 0.0, 100.0))

        reasons: list[str] = []
        priority = "ok"
        if ident in known_male:
            priority = "alta"
            score = 100.0
            reasons.append("voz masculina confirmada por escuta")
        elif f0 <= 155.0 and under160 >= 0.70:
            priority = "alta"
            reasons.append("pitch predominantemente em faixa masculina")
        elif f0 <= 168.0 and under170 >= 0.70:
            priority = "media"
            reasons.append("forte indicio de pitch masculino")
        elif f0 <= 180.0 and under180 >= 0.70:
            priority = "baixa"
            reasons.append("pitch abaixo do padrao feminino; conferir")
        elif z_style <= -3.5 and under170 >= 0.45:
            priority = "baixa"
            reasons.append("outlier grave de pitch dentro do estilo")

        if under150 >= 0.65:
            reasons.append(f"{under150:.0%} dos quadros abaixo de 150 Hz")
        elif under160 >= 0.65:
            reasons.append(f"{under160:.0%} dos quadros abaixo de 160 Hz")
        if z_style <= -3.0:
            reasons.append(f"pitch {abs(z_style):.1f} desvios robustos abaixo do estilo")

        row.update(
            {
                "z_pitch_estilo": round(z_style, 4),
                "risco_identidade": round(score, 2),
                "prioridade_identidade": priority,
                "motivos_identidade": " | ".join(reasons),
            }
        )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--base-wav-dir", type=Path, required=True)
    parser.add_argument("--overlay-wav-dir", type=Path, action="append", default=[])
    parser.add_argument("--fallback-wav-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--known-male", action="append", default=[])
    args = parser.parse_args()

    known_male = {normalize_id(value) for value in args.known_male}
    items = build_items(
        args.jsonl.resolve(),
        args.assignments.resolve(),
        args.base_wav_dir.resolve(),
        [path.resolve() for path in args.overlay_wav_dir],
        args.fallback_wav_dir.resolve() if args.fallback_wav_dir else None,
    )
    print(f"WAVs finais selecionados: {len(items)}; workers={args.workers}", flush=True)

    started = time.monotonic()
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(extract_features, item): item for item in items}
        completed = 0
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - cada WAV deve gerar uma linha
                result = {
                    "id_hex": item.ident,
                    "texto": item.text,
                    "estilo": item.estilo,
                    "fonte": item.fonte,
                    "wav": str(item.path),
                    "erro": str(exc),
                }
            results.append(result)
            completed += 1
            if completed == 1 or completed % 500 == 0 or completed == len(items):
                elapsed = time.monotonic() - started
                rate = completed / max(elapsed, 1e-9)
                remaining = (len(items) - completed) / max(rate, 1e-9)
                print(
                    f"Progresso: {completed}/{len(items)} "
                    f"({rate:.1f} WAV/s; restante ~{remaining/60:.1f} min)",
                    flush=True,
                )

    classify(results, known_male)
    priority_order = {"alta": 0, "media": 1, "baixa": 2, "ok": 3}
    results.sort(
        key=lambda row: (
            priority_order.get(str(row["prioridade_identidade"]), 9),
            -float(row["risco_identidade"]),
            str(row["id_hex"]),
        )
    )
    write_csv(args.output.resolve(), results)

    counts: dict[str, int] = {}
    sources: dict[str, int] = {}
    for row in results:
        key = str(row["prioridade_identidade"])
        counts[key] = counts.get(key, 0) + 1
        source = str(row["fonte"])
        sources[source] = sources.get(source, 0) + 1
    summary = {
        "total": len(results),
        "contagens_prioridade": counts,
        "fontes": sources,
        "casos_confirmados": sorted(known_male),
        "duracao_execucao_s": round(time.monotonic() - started, 3),
        "relatorio": str(args.output.resolve()),
        "observacao": "Triagem heuristica; candidatos exigem escuta humana.",
    }
    args.summary.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.summary.resolve().write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
