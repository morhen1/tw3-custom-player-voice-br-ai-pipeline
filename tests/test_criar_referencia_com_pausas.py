from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "criar_referencia_com_pausas.py"
SPEC = importlib.util.spec_from_file_location("criar_referencia_com_pausas", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PauseReferenceTests(unittest.TestCase):
    def test_detects_internal_silence_and_inserts_requested_samples(self) -> None:
        sample_rate = 1000
        audio = np.concatenate(
            (
                np.full(300, 0.5, dtype=np.float32),
                np.zeros(150, dtype=np.float32),
                np.full(300, 0.5, dtype=np.float32),
            )
        )
        intervals = MODULE.detect_pauses(
            audio,
            sample_rate,
            threshold_db=-30.0,
            minimum_ms=100.0,
            ignore_edge_ms=50.0,
        )
        self.assertEqual(len(intervals), 1)
        adjusted = MODULE.insert_silence(audio, intervals, extra_samples=180)
        self.assertEqual(len(adjusted), len(audio) + 180)


if __name__ == "__main__":
    unittest.main()
