from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from preparar_dataset import PreparationError, clean_markup, main, read_lines_csv


class CleanMarkupTests(unittest.TestCase):
    def test_remove_known_action(self) -> None:
        text, removed, unknown = clean_markup("*Suspira* Estou pronta.")
        self.assertEqual(text, "Estou pronta.")
        self.assertEqual(removed, ["Suspira"])
        self.assertEqual(unknown, [])

    def test_preserve_emphasis_without_asterisks(self) -> None:
        text, removed, unknown = clean_markup("Que bom que *eu* o encontrei...")
        self.assertEqual(text, "Que bom que eu o encontrei...")
        self.assertEqual(removed, [])
        self.assertEqual(unknown, ["eu"])

    def test_action_only_becomes_empty(self) -> None:
        text, _removed, _unknown = clean_markup("*Cof* *Cof* *Cof*")
        self.assertEqual(text, "")


class LinesCsvTests(unittest.TestCase):
    def write(self, contents: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "sample.lines.csv"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_identical_duplicates_are_deduplicated(self) -> None:
        path = self.write("1|00000000||Olá.\n1|00000000||Olá.\n")
        rows = read_lines_csv(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_lines, (1, 2))

    def test_conflicting_duplicates_fail(self) -> None:
        path = self.write("1|00000000||Olá.\n1|00000000||Adeus.\n")
        with self.assertRaises(PreparationError):
            read_lines_csv(path)


class JsonlDurationTests(unittest.TestCase):
    def run_preparation(self, include_duration: bool) -> dict[str, object]:
        directory = Path(tempfile.mkdtemp())
        lines = directory / "lines.csv"
        durations = directory / "durations.csv"
        reference = directory / "reference.wav"
        reference_text = directory / "reference.txt"
        jsonl = directory / "output.jsonl"
        report = directory / "report.csv"
        lines.write_text("1|00000000||Olá.\n", encoding="utf-8")
        durations.write_text(
            "id_hex;duracao_segundos;canais;status\n0x00000001;1.250000;1;ok\n",
            encoding="utf-8",
        )
        reference.write_bytes(b"placeholder")
        reference_text.write_text("Texto da referência.", encoding="utf-8")
        argv = [
            "preparar_dataset.py",
            "--lines", str(lines),
            "--durations", str(durations),
            "--ref-audio", str(reference),
            "--ref-text-file", str(reference_text),
            "--jsonl", str(jsonl),
            "--report", str(report),
            "--require-durations",
        ]
        if include_duration:
            argv.append("--include-duration-in-jsonl")
        with patch("sys.argv", argv):
            self.assertEqual(main(), 0)
        return json.loads(jsonl.read_text(encoding="utf-8"))

    def test_duration_is_omitted_by_default(self) -> None:
        payload = self.run_preparation(False)
        self.assertNotIn("duration", payload)

    def test_duration_requires_explicit_legacy_flag(self) -> None:
        payload = self.run_preparation(True)
        self.assertEqual(payload["duration"], 1.25)


if __name__ == "__main__":
    unittest.main()
