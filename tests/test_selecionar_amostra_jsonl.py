from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "selecionar_amostra_jsonl.py"
SPEC = importlib.util.spec_from_file_location("selecionar_amostra_jsonl", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SelectionTests(unittest.TestCase):
    def test_spans_duration_range_and_preserves_required_id(self) -> None:
        candidates = [
            MODULE.Candidate(f"0x{index:08x}", float(index), {"id": f"0x{index:08x}"})
            for index in range(1, 101)
        ]
        chosen = MODULE.choose_evenly(candidates, 10, ["0x0000002a"])
        ids = {item.ident for item in chosen}
        self.assertEqual(len(chosen), 10)
        self.assertIn("0x0000002a", ids)
        self.assertEqual(min(item.duration for item in chosen), 1.0)
        self.assertGreaterEqual(max(item.duration for item in chosen), 90.0)


if __name__ == "__main__":
    unittest.main()
