#!/usr/bin/env python3
"""Converte em lotes WAVs hexadecimais do Geralt para WEM Opus do TW3 4.04.

O script usa diretamente o comando ``convert-external-source`` do
WwiseConsole. Assim, cada lote abre o Wwise apenas uma vez, em vez de uma vez
por áudio. O ShareSet ``WEMOpusSpeech`` precisa existir e estar salvo no
projeto do sound2wem.

Características de segurança:

* nunca modifica os WAVs;
* grava os WEMs em uma pasta nova;
* valida RIFF, codec 0x3041, quantidade de canais e 48 kHz;
* retoma automaticamente, pulando resultados já válidos;
* converte primeiro um único arquivo como pré-teste;
* conserva a pasta de diagnóstico quando um lote falha.

Uso normal:

    py -3 converter_wav_para_wem_opus_lote_v2.py \
        --input saida/wav_final --output saida/wem_opus_mono \
        --wwise-console "C:/caminho/WwiseConsole.exe" \
        --project "C:/caminho/projeto.wproj"

Teste de cinco arquivos:

    py -3 converter_wav_para_wem_opus_lote_v2.py --limit 5

Somente auditoria, sem chamar o Wwise:

    py -3 converter_wav_para_wem_opus_lote_v2.py --check-only
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SHARESET = "WEMOpusSpeech"

WEM_NAME_RE = re.compile(r"^0x([0-9a-fA-F]{8})\.wav$", re.IGNORECASE)
U32 = struct.Struct("<I")
FMT_BASE = struct.Struct("<HHIIHH")
EXPECTED_TAG = 0x3041
EXPECTED_RATE = 48_000


class ConversionError(RuntimeError):
    """Falha de configuração, conversão ou validação."""


@dataclass(frozen=True)
class WemInfo:
    format_tag: int
    fmt_size: int
    channels: int
    sample_rate: int
    avg_bytes_per_sec: int
    data_size: int
    chunks: tuple[str, ...]
    file_size: int

    def valid_for_tw3_speech(self, expected_channels: int) -> bool:
        return (
            self.format_tag == EXPECTED_TAG
            and self.fmt_size == 36
            and self.channels == expected_channels
            and self.sample_rate == EXPECTED_RATE
            and self.avg_bytes_per_sec > 0
            and self.data_size > 0
            and "seek" in self.chunks
        )

    @property
    def description(self) -> str:
        return (
            f"tag=0x{self.format_tag:04x}, fmt={self.fmt_size}, "
            f"{self.channels}ch/{self.sample_rate}Hz, {self.file_size} bytes, "
            f"chunks={','.join(self.chunks)}"
        )


@dataclass(frozen=True)
class ItemResult:
    name: str
    status: str
    detail: str


def parse_wem(path: Path) -> WemInfo:
    """Lê apenas o necessário do contêiner RIFF/WEM e valida seus limites."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConversionError(f"não foi possível ler {path}: {exc}") from exc

    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ConversionError("assinatura RIFF/WAVE ausente")
    declared_size = U32.unpack_from(data, 4)[0] + 8
    if declared_size != len(data):
        raise ConversionError(
            f"RIFF declara {declared_size} bytes, arquivo possui {len(data)}"
        )

    pos = 12
    fmt: tuple[int, int, int, int, int, int] | None = None
    fmt_size = 0
    data_size: int | None = None
    chunks: list[str] = []
    while pos + 8 <= len(data):
        chunk_id = data[pos : pos + 4]
        chunk_size = U32.unpack_from(data, pos + 4)[0]
        payload = pos + 8
        end = payload + chunk_size
        if end > len(data):
            raise ConversionError(f"chunk {chunk_id!r} excede o arquivo")
        chunks.append(chunk_id.decode("ascii", errors="replace"))
        if chunk_id == b"fmt ":
            if chunk_size < FMT_BASE.size:
                raise ConversionError("chunk fmt pequeno demais")
            fmt = FMT_BASE.unpack_from(data, payload)
            fmt_size = chunk_size
        elif chunk_id == b"data":
            data_size = chunk_size
        pos = end + (chunk_size & 1)

    if fmt is None or data_size is None:
        raise ConversionError("chunks fmt/data ausentes")
    tag, channels, rate, avg_bps, _align, _bits = fmt
    return WemInfo(
        format_tag=tag,
        fmt_size=fmt_size,
        channels=channels,
        sample_rate=rate,
        avg_bytes_per_sec=avg_bps,
        data_size=data_size,
        chunks=tuple(chunks),
        file_size=len(data),
    )


def validate_output(path: Path, expected_channels: int) -> tuple[bool, str]:
    if not path.is_file():
        return False, "arquivo não encontrado"
    try:
        info = parse_wem(path)
    except ConversionError as exc:
        return False, str(exc)
    if not info.valid_for_tw3_speech(expected_channels):
        return False, info.description
    return True, info.description


def iter_wavs(input_dir: Path) -> tuple[list[Path], list[str]]:
    wavs: list[Path] = []
    ignored: list[str] = []
    for path in input_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".wav":
            continue
        if WEM_NAME_RE.fullmatch(path.name):
            wavs.append(path)
        else:
            ignored.append(path.name)
    wavs.sort(key=lambda path: int(WEM_NAME_RE.fullmatch(path.name).group(1), 16))
    ignored.sort()
    return wavs, ignored


def chunks(items: Sequence[Path], size: int) -> Iterable[list[Path]]:
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def write_external_sources(
    manifest: Path,
    input_dir: Path,
    wavs: Sequence[Path],
    shareset: str,
) -> None:
    root = ET.Element(
        "ExternalSourcesList",
        {"SchemaVersion": "1", "Root": str(input_dir)},
    )
    for wav in wavs:
        ET.SubElement(
            root,
            "Source",
            {"Path": wav.name, "Conversion": shareset},
        )
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(manifest, encoding="utf-8", xml_declaration=True)


def expected_temp_wem(output_root: Path, wav: Path) -> Path | None:
    name = wav.with_suffix(".wem").name
    usual = output_root / "Windows" / name
    if usual.is_file():
        return usual
    direct = output_root / name
    if direct.is_file():
        return direct
    matches = list(output_root.rglob(name))
    return matches[0] if len(matches) == 1 else None


def run_wwise_batch(
    *,
    wavs: Sequence[Path],
    batch_number: int,
    total_batches: int,
    args: argparse.Namespace,
    label: str | None = None,
) -> list[ItemResult]:
    batch_dir = Path(
        tempfile.mkdtemp(
            prefix=f"batch_{batch_number:04d}_",
            dir=args.work_dir,
        )
    )
    output_root = batch_dir / "output"
    output_root.mkdir()
    manifest = batch_dir / "list.wsources"
    log_path = batch_dir / "wwise.log"
    write_external_sources(manifest, args.input, wavs, args.shareset)

    command = [
        str(args.wwise_console),
        "convert-external-source",
        str(args.project),
        "--source-file",
        str(manifest),
        "--output",
        str(output_root),
        "--quiet",
    ]
    display_label = label or f"Lote {batch_number}/{total_batches}"
    print(
        f"{display_label}: chamando o Wwise para {len(wavs)} arquivo(s)...",
        flush=True,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=args.project.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise ConversionError(f"não foi possível iniciar o WwiseConsole: {exc}") from exc
    log_path.write_text(completed.stdout or "", encoding="utf-8")

    results: list[ItemResult] = []
    for wav in wavs:
        final_path = args.output / wav.with_suffix(".wem").name
        temp_wem = expected_temp_wem(output_root, wav)
        if temp_wem is None:
            results.append(ItemResult(wav.name, "falha", "WEM não foi produzido"))
            continue
        valid, detail = validate_output(temp_wem, args.expected_channels)
        if not valid:
            results.append(ItemResult(wav.name, "falha", f"WEM incompatível: {detail}"))
            continue
        os.replace(temp_wem, final_path)
        results.append(ItemResult(wav.name, "convertido", detail))

    failures = [item for item in results if item.status == "falha"]
    if completed.returncode != 0 and not failures:
        # Um código de saída diferente de zero nunca deve ser ocultado, mesmo se
        # o Wwise deixou arquivos aparentemente válidos.
        raise ConversionError(
            f"WwiseConsole terminou com código {completed.returncode}; veja {log_path}"
        )

    if failures:
        print(
            f"  {len(failures)} falha(s); diagnóstico preservado em {batch_dir}",
            flush=True,
        )
    else:
        shutil.rmtree(batch_dir)
    return results


def write_report(path: Path, results: Sequence[ItemResult]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    with partial.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["arquivo", "status", "detalhe"])
        for item in results:
            writer.writerow([item.name, item.status, item.detail])
    os.replace(partial, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Converte WAVs 0x12345678.wav para WEM Opus de 1 ou 2 canais/48 kHz."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wwise-console", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shareset", default=DEFAULT_SHARESET)
    parser.add_argument(
        "--expected-channels",
        type=int,
        choices=(1, 2),
        default=1,
        help="quantidade de canais exigida nos WEMs gerados (padrão: 1)",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, help="processar somente os primeiros N")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--only-id",
        help="processar somente um ID, por exemplo 0x000f4f9c",
    )
    selection.add_argument(
        "--ids-file",
        type=Path,
        help="TXT com um ID hexadecimal por linha; linhas # são comentários",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="auditar entradas e WEMs existentes sem converter",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="reconverter também WEMs existentes que já são válidos",
    )
    return parser


def resolve_args(args: argparse.Namespace) -> None:
    args.input = args.input.resolve()
    args.output = args.output.resolve()
    args.wwise_console = args.wwise_console.resolve()
    args.project = args.project.resolve()
    if args.ids_file is not None:
        args.ids_file = args.ids_file.resolve()
    args.work_dir = args.output / "_wwise_work"

    if args.batch_size < 1 or args.batch_size > 5000:
        raise ConversionError("--batch-size deve estar entre 1 e 5000")
    if args.limit is not None and args.limit < 1:
        raise ConversionError("--limit deve ser maior que zero")
    if not args.input.is_dir():
        raise ConversionError(f"pasta de WAVs não encontrada: {args.input}")
    if args.ids_file is not None and not args.ids_file.is_file():
        raise ConversionError(f"lista de IDs não encontrada: {args.ids_file}")
    if not args.check_only:
        if not args.wwise_console.is_file():
            raise ConversionError(f"WwiseConsole não encontrado: {args.wwise_console}")
        if not args.project.is_file():
            raise ConversionError(f"projeto Wwise não encontrado: {args.project}")
        if not args.shareset.strip():
            raise ConversionError("nome do ShareSet vazio")


def select_wavs(args: argparse.Namespace) -> tuple[list[Path], list[str]]:
    wavs, ignored = iter_wavs(args.input)
    if args.only_id:
        try:
            ident = int(args.only_id, 0)
        except ValueError as exc:
            raise ConversionError(f"ID inválido: {args.only_id}") from exc
        if not 0 <= ident <= 0xFFFFFFFF:
            raise ConversionError(f"ID fora de uint32: {args.only_id}")
        wanted = f"0x{ident:08x}.wav"
        wavs = [path for path in wavs if path.name.lower() == wanted]
        if not wavs:
            raise ConversionError(f"{wanted} não encontrado em {args.input}")
    elif args.ids_file is not None:
        wanted_ids: set[int] = set()
        for line_number, raw_line in enumerate(
            args.ids_file.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            token = raw_line.split("#", 1)[0].strip()
            if not token:
                continue
            try:
                ident = int(token, 0)
            except ValueError as exc:
                raise ConversionError(
                    f"{args.ids_file}, linha {line_number}: ID inválido {token!r}"
                ) from exc
            if not 0 <= ident <= 0xFFFFFFFF:
                raise ConversionError(
                    f"{args.ids_file}, linha {line_number}: ID fora de uint32"
                )
            if ident in wanted_ids:
                raise ConversionError(
                    f"{args.ids_file}, linha {line_number}: ID repetido 0x{ident:08x}"
                )
            wanted_ids.add(ident)
        if not wanted_ids:
            raise ConversionError(f"nenhum ID encontrado em {args.ids_file}")
        by_id = {
            int(WEM_NAME_RE.fullmatch(path.name).group(1), 16): path for path in wavs
        }
        missing = sorted(wanted_ids - set(by_id))
        if missing:
            preview = ", ".join(f"0x{ident:08x}" for ident in missing[:20])
            suffix = "" if len(missing) <= 20 else f" e mais {len(missing) - 20}"
            raise ConversionError(
                f"{len(missing)} WAV(s) da lista não encontrado(s): {preview}{suffix}"
            )
        wavs = [by_id[ident] for ident in sorted(wanted_ids)]
    if args.limit is not None:
        wavs = wavs[: args.limit]
    if not wavs:
        raise ConversionError("nenhum WAV hexadecimal foi encontrado")
    return wavs, ignored


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        resolve_args(args)
        wavs, ignored = select_wavs(args)
        print(f"WAVs selecionados: {len(wavs)}")
        if ignored:
            print(f"WAVs com nome inválido ignorados: {len(ignored)}")

        results_by_name: dict[str, ItemResult] = {}
        pending: list[Path] = []
        valid_existing = 0
        invalid_existing = 0
        for wav in wavs:
            output = args.output / wav.with_suffix(".wem").name
            if output.exists():
                valid, detail = validate_output(output, args.expected_channels)
                if valid:
                    valid_existing += 1
                    results_by_name[wav.name] = ItemResult(
                        wav.name, "já_válido", detail
                    )
                    if args.force:
                        pending.append(wav)
                else:
                    invalid_existing += 1
                    results_by_name[wav.name] = ItemResult(
                        wav.name, "existente_inválido", detail
                    )
                    pending.append(wav)
            else:
                pending.append(wav)

        print(
            f"Existentes válidos: {valid_existing}; "
            f"existentes incompatíveis: {invalid_existing}; pendentes: {len(pending)}"
        )
        if args.check_only:
            print("Auditoria concluída; nenhum arquivo foi alterado.")
            return 0
        if not pending:
            print("Todos os WEMs selecionados já estão válidos.")
            return 0

        args.output.mkdir(parents=True, exist_ok=True)
        args.work_dir.mkdir(parents=True, exist_ok=True)

        # O primeiro arquivo é propositalmente isolado. Isso impede que uma
        # configuração errada do ShareSet produza milhares de WEMs PCM/Vorbis
        # ou Opus em 24 kHz antes de ser detectada.
        preflight = run_wwise_batch(
            wavs=[pending[0]],
            batch_number=0,
            total_batches=1,
            args=args,
            label="Pré-teste",
        )
        results_by_name[preflight[0].name] = preflight[0]
        if preflight[0].status != "convertido":
            report = args.output / "relatorio_conversao_wem_opus.csv"
            write_report(report, list(results_by_name.values()))
            raise ConversionError(
                "pré-teste falhou; nenhum lote grande foi iniciado. "
                f"Consulte {report} e a pasta {args.work_dir}"
            )
        print(
            "Pré-teste aprovado: WEM Opus 0x3041, "
            f"{args.expected_channels} canal(is), 48 kHz."
        )

        remaining = pending[1:]
        batches = list(chunks(remaining, args.batch_size))
        for number, batch in enumerate(batches, start=1):
            results = run_wwise_batch(
                wavs=batch,
                batch_number=number,
                total_batches=len(batches),
                args=args,
            )
            for item in results:
                results_by_name[item.name] = item

            # Um WAV defeituoso não deve condenar o lote inteiro. Os itens que
            # não saíram válidos são tentados isoladamente e ficam claramente
            # identificados no relatório se falharem de novo.
            failed_names = [item.name for item in results if item.status == "falha"]
            if failed_names:
                wav_by_name = {wav.name: wav for wav in batch}
                print(f"  Tentando {len(failed_names)} falha(s) individualmente...")
                for retry_index, name in enumerate(failed_names, start=1):
                    retry = run_wwise_batch(
                        wavs=[wav_by_name[name]],
                        batch_number=number * 10_000 + retry_index,
                        total_batches=number * 10_000 + len(failed_names),
                        args=args,
                        label=(
                            f"Nova tentativa individual {retry_index}/"
                            f"{len(failed_names)} (lote {number})"
                        ),
                    )[0]
                    results_by_name[name] = retry

            completed_now = sum(
                item.status in {"convertido", "já_válido"}
                for item in results_by_name.values()
            )
            print(
                f"  Progresso total selecionado: {completed_now}/{len(wavs)} válidos",
                flush=True,
            )

        report = args.output / "relatorio_conversao_wem_opus.csv"
        ordered_results = [results_by_name[wav.name] for wav in wavs]
        write_report(report, ordered_results)
        final_valid = 0
        for wav in wavs:
            valid, _detail = validate_output(
                args.output / wav.with_suffix(".wem").name,
                args.expected_channels,
            )
            final_valid += int(valid)

        print(f"WEMs válidos ao final: {final_valid}/{len(wavs)}")
        print(f"Relatório: {report}")
        if final_valid != len(wavs):
            print(
                "A execução terminou com falhas. Rode novamente para retomar; "
                "os WEMs válidos serão pulados.",
                file=sys.stderr,
            )
            return 2
        print("Conversão concluída com todos os resultados validados.")
        return 0
    except (ConversionError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
