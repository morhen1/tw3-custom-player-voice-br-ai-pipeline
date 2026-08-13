from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "analisar_prosodia_comparativa.py"
SPEC = importlib.util.spec_from_file_location("analisar_prosodia_comparativa", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProsodyComparisonTests(unittest.TestCase):
    def test_count_runs_uses_minimum_length(self) -> None:
        mask = [False, True, True, False, True, True, True, False]
        self.assertEqual(MODULE.count_runs(mask, minimum_frames=3), 1)

    def test_summary_describes_more_expressive_old_set(self) -> None:
        rows = [
            {
                "antigo_duration_s": 0.8,
                "atual_duration_s": 1.0,
                "antigo_pitch_span_st": 6.0,
                "atual_pitch_span_st": 4.0,
                "antigo_pitch_motion_st": 0.5,
                "atual_pitch_motion_st": 0.2,
                "antigo_energy_span_db": 8.0,
                "atual_energy_span_db": 5.0,
                "antigo_pause_ratio": 0.12,
                "atual_pause_ratio": 0.05,
            }
        ]
        summary = MODULE.summarize(rows)
        self.assertEqual(summary["pares_validos"], 1)
        self.assertEqual(summary["mediana_razao_duracao_antigo_atual"], 0.8)
        observations = " ".join(summary["observacoes"])
        self.assertIn("maior amplitude de entonação", observations)
        self.assertIn("maior contraste de intensidade", observations)


if __name__ == "__main__":
    unittest.main()
