#!/usr/bin/env python3
"""Prepara falas do Geralt para uma voz de jogadora feminina no OmniVoice.

O programa é conservador: remove apenas marcações não verbais conhecidas,
deduplica IDs equivalentes e aplica correções explícitas por ID. Marcações
desconhecidas e possíveis concordâncias de gênero são enviadas ao relatório.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


MARKUP_RE = re.compile(r"\*+([^*]+?)\*+")
ONLY_PUNCTUATION_RE = re.compile(r"^[\s.…,;:!?—–-]*$")
NONVERBAL = {
    "assobia", "assobio", "cheira", "cheirando", "cof", "cof cof",
    "cof, cof", "hrrm", "risos", "snif", "sniff", "suspira", "suspiro",
    "tsc", "zomba",
}
FIRST_PERSON_RE = re.compile(
    r"\b(?:eu|sou|estou|fui|era|fico|fiquei|continuo|me sinto|obrigado)\b",
    re.IGNORECASE,
)
MASCULINE_RE = re.compile(
    r"\b(?:obrigado|cansado|preocupado|pronto|sozinho|machucado|ferido|"
    r"assustado|aliviado|certo|errado|convencido|surpreso|perdido|"
    r"amaldiçoado|encantado|satisfeito|orgulhoso|ocupado)\b",
    re.IGNORECASE,
)


class PreparationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceLine:
    ident: int
    text: str
    source_lines: tuple[int, ...]


@dataclass(frozen=True)
class Correction:
    action: str
    text: str
    reason: str


def hex_id(ident: int) -> str:
    return f"0x{ident:08x}"


def read_lines_csv(path: Path) -> list[SourceLine]:
    by_id: dict[int, tuple[str, list[int]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip() or raw.lstrip().startswith(";"):
                continue
            parts = raw.rstrip("\r\n").split("|")
            token = parts[0].strip()
            if not token.isdecimal() or len(parts) < 2:
                continue
            ident = int(token)
            if not 0 <= ident <= 0xFFFFFFFF:
                raise PreparationError(f"linha {line_number}: ID fora de uint32")
            text = parts[-1].strip()
            if not text:
                continue
            previous = by_id.get(ident)
            if previous is None:
                by_id[ident] = (text, [line_number])
            elif previous[0] == text:
                previous[1].append(line_number)
            else:
                raise PreparationError(
                    f"ID {hex_id(ident)} possui textos conflitantes nas linhas "
                    f"{previous[1][0]} e {line_number}"
                )
    if not by_id:
        raise PreparationError(f"nenhuma fala encontrada em {path}")
    return [
        SourceLine(ident, text, tuple(lines))
        for ident, (text, lines) in sorted(by_id.items())
    ]


def read_corrections(path: Path | None) -> dict[int, Correction]:
    if path is None or not path.exists():
        return {}
    result: dict[int, Correction] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"id_hex", "acao", "texto", "motivo"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise PreparationError(
                f"{path}: cabeçalho esperado: id_hex;acao;texto;motivo"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                ident = int((row["id_hex"] or "").strip(), 0)
            except ValueError as exc:
                raise PreparationError(
                    f"{path}, linha {line_number}: ID inválido"
                ) from exc
            action = (row["acao"] or "gerar").strip().lower()
            if action not in {"gerar", "usar_original"}:
                raise PreparationError(
                    f"{path}, linha {line_number}: ação deve ser gerar ou usar_original"
                )
            if ident in result:
                raise PreparationError(f"{path}: correção duplicada para {hex_id(ident)}")
            result[ident] = Correction(
                action, (row["texto"] or "").strip(), (row["motivo"] or "").strip()
            )
    return result


def read_durations(path: Path | None) -> dict[int, tuple[float, int]]:
    if path is None or not path.exists():
        return {}
    result: dict[int, tuple[float, int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for line_number, row in enumerate(reader, start=2):
            if (row.get("status") or "ok").strip().lower() != "ok":
                continue
            if not (row.get("duracao_segundos") or "").strip():
                continue
            try:
                ident = int((row.get("id_hex") or "").strip(), 0)
                duration = float((row.get("duracao_segundos") or "").replace(",", "."))
                channels = int(row.get("canais") or 1)
            except ValueError as exc:
                raise PreparationError(
                    f"{path}, linha {line_number}: metadado inválido"
                ) from exc
            if duration <= 0 or channels not in {1, 2}:
                raise PreparationError(f"{path}, linha {line_number}: duração/canais inválidos")
            old = result.get(ident)
            if old and (abs(old[0] - duration) > 0.02 or old[1] != channels):
                raise PreparationError(f"{path}: metadados conflitantes para {hex_id(ident)}")
            result[ident] = (duration, channels)
    return result


def clean_markup(text: str) -> tuple[str, list[str], list[str]]:
    removed: list[str] = []
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        token = " ".join(match.group(1).strip().split())
        if token.casefold() in NONVERBAL:
            removed.append(token)
            return ""
        unknown.append(token)
        return token

    cleaned = MARKUP_RE.sub(replace, text)
    # Remove espaços criados pela retirada, sem reescrever a pontuação original.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    cleaned = re.sub(r"^\s*[,;:]\s*", "", cleaned)
    return cleaned, removed, unknown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=Path, required=True)
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--durations", type=Path)
    parser.add_argument("--ref-audio", type=Path, required=True)
    parser.add_argument("--ref-text-file", type=Path, required=True)
    parser.add_argument("--jsonl", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--language-id", default="pt")
    parser.add_argument("--language-name", default="Portuguese (Brazil)")
    parser.add_argument("--require-durations", action="store_true")
    parser.add_argument(
        "--include-duration-in-jsonl",
        action="store_true",
        help=(
            "modo legado: envia a duração original ao OmniVoice; pode cortar "
            "palavras e não é recomendado para a geração final"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if not args.lines.is_file():
            raise PreparationError(f"CSV não encontrado: {args.lines}")
        if not args.ref_audio.is_file():
            raise PreparationError(f"áudio de referência não encontrado: {args.ref_audio}")
        if not args.ref_text_file.is_file():
            raise PreparationError(f"transcrição da referência não encontrada: {args.ref_text_file}")
        ref_text = args.ref_text_file.read_text(encoding="utf-8-sig").strip()
        if not ref_text:
            raise PreparationError("a transcrição da referência está vazia")

        lines = read_lines_csv(args.lines)
        corrections = read_corrections(args.corrections)
        durations = read_durations(args.durations)
        unknown_corrections = sorted(set(corrections) - {item.ident for item in lines})
        if unknown_corrections:
            preview = ", ".join(hex_id(item) for item in unknown_corrections[:10])
            raise PreparationError(f"correções para IDs ausentes do corpus: {preview}")

        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        report_rows: list[list[str]] = []
        generated = 0
        use_original = 0
        review = 0
        missing_duration = 0

        with args.jsonl.open("w", encoding="utf-8", newline="\n") as jsonl:
            for item in lines:
                cleaned, removed, unknown = clean_markup(item.text)
                correction = corrections.get(item.ident)
                action = "gerar"
                reason_parts: list[str] = []
                if removed:
                    reason_parts.append("ações removidas: " + ", ".join(removed))
                if unknown:
                    reason_parts.append("marcação desconhecida preservada: " + ", ".join(unknown))
                if correction:
                    action = correction.action
                    if correction.text:
                        cleaned = correction.text
                    reason_parts.append("correção manual: " + (correction.reason or "sem motivo"))
                elif not cleaned or ONLY_PUNCTUATION_RE.fullmatch(cleaned):
                    action = "usar_original"
                    reason_parts.append("linha sem fala lexical após limpeza")

                flags: list[str] = []
                if unknown and correction is None:
                    flags.append("revisar_marcacao")
                if (
                    action == "gerar"
                    and correction is None
                    and FIRST_PERSON_RE.search(cleaned)
                    and MASCULINE_RE.search(cleaned)
                ):
                    flags.append("revisar_genero")
                metadata = durations.get(item.ident)
                if action == "gerar" and metadata is None:
                    flags.append("duracao_ausente")
                    missing_duration += 1
                if flags:
                    review += 1
                if action == "usar_original":
                    use_original += 1
                else:
                    payload: dict[str, object] = {
                        "id": hex_id(item.ident),
                        "text": cleaned,
                        "language_id": args.language_id,
                        "language_name": args.language_name,
                        "ref_audio": str(args.ref_audio.resolve()),
                        "ref_text": ref_text,
                    }
                    if metadata and args.include_duration_in_jsonl:
                        payload["duration"] = round(metadata[0], 3)
                    jsonl.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    generated += 1
                report_rows.append([
                    hex_id(item.ident), action, item.text, cleaned,
                    f"{metadata[0]:.6f}" if metadata else "",
                    str(metadata[1]) if metadata else "",
                    ",".join(flags), " | ".join(reason_parts),
                    ",".join(str(number) for number in item.source_lines),
                ])

        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([
                "id_hex", "acao", "texto_original", "texto_final",
                "duracao_original", "canais_originais", "revisar", "detalhe",
                "linhas_fonte",
            ])
            writer.writerows(report_rows)

        print(f"IDs únicos: {len(lines)}; gerar={generated}; usar_original={use_original}")
        print(f"Linhas sinalizadas para revisão: {review}")
        print(f"Durações ausentes entre as falas geradas: {missing_duration}")
        print(
            "Duração enviada ao OmniVoice: "
            + ("sim (modo legado)" if args.include_duration_in_jsonl else "não")
        )
        print(f"JSONL: {args.jsonl}")
        print(f"Relatório: {args.report}")
        if args.require_durations and missing_duration:
            raise PreparationError("há falas geráveis sem duração original")
        return 0
    except (PreparationError, OSError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
