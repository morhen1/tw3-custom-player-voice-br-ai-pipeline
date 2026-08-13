from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from aplicar_correcoes_jsonl import read_corrections


class ReadCorrectionsTests(unittest.TestCase):
    def test_reads_explicit_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "correcoes.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["id_hex", "texto"])
                writer.writerow(["0x0011a756", "Não houve problema?"])
            self.assertEqual(
                read_corrections(path), {"0x0011a756": "Não houve problema?"}
            )


if __name__ == "__main__":
    unittest.main()
