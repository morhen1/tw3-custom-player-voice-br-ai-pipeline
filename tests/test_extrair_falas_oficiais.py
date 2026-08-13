from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from extrair_falas_oficiais import extract_official_wems
from montar_brpc_w3speech_compacto_v4 import ENTRY_STRUCT


def make_wem() -> bytes:
    fmt_base = struct.pack("<HHIIHH", 0x3041, 1, 48_000, 12_000, 0, 0)
    fmt_payload = fmt_base + bytes(20)
    data_payload = bytes(range(120))
    wave = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt_payload))
        + fmt_payload
        + b"data"
        + struct.pack("<I", len(data_payload))
        + data_payload
    )
    return b"RIFF" + struct.pack("<I", len(wave)) + wave


def make_archive(path: Path, ident: int, wem: bytes) -> None:
    header_size = 4 + 4 + 2 + 1 + ENTRY_STRUCT.size + 2
    wave_size = len(wem) + 12
    entry = ENTRY_STRUCT.pack(
        ident,
        0,
        header_size,
        0,
        wave_size,
        0,
        0,
        0,
        0,
        0,
    )
    trailer = struct.pack("<fI", 0.01, 0)
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"CPSW"
        + struct.pack("<I", 163)
        + struct.pack("<H", 0)
        + b"\x01"
        + entry
        + struct.pack("<H", 0)
        + struct.pack("<I", len(wem))
        + wem
        + trailer
    )


class ExtractOfficialSpeechTests(unittest.TestCase):
    def test_extracts_and_validates_official_wem(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            ident = 0x000F4F9C
            wem = make_wem()
            game_root = tmp_path / "game"
            archive = game_root / "content" / "content0" / "brpc.w3speech"
            make_archive(archive, ident, wem)
            output = tmp_path / "wems"
            report = tmp_path / "report.csv"

            rows, errors = extract_official_wems(
                game_root,
                [ident],
                output,
                report,
            )

            self.assertEqual(errors, [])
            self.assertEqual(rows[0].status, "ok")
            self.assertEqual(rows[0].codec, "wem-opus")
            self.assertEqual((output / "0x000f4f9c.wem").read_bytes(), wem)
            self.assertTrue(report.is_file())


if __name__ == "__main__":
    unittest.main()
