from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "selecionar_referencias_expressivas.py"
SPEC = importlib.util.spec_from_file_location("selecionar_referencias_expressivas", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ExpressiveSelectionTests(unittest.TestCase):
    def test_questions_and_internal_punctuation_receive_higher_score(self) -> None:
        plain = MODULE.text_preselection_score("Uma frase completamente neutra", 6.5)
        expressive = MODULE.text_preselection_score(
            "Espere... Você realmente fez isso? Não pode ser!", 6.5
        )
        self.assertGreater(expressive, plain)

    def test_expression_score_prefers_larger_prosodic_variation(self) -> None:
        rows = [
            {
                "pitch_span_st": 2.0,
                "pitch_std_st": 1.0,
                "pitch_motion_st": 0.1,
                "energy_span_db": 10.0,
                "pause_ratio": 0.1,
            },
            {
                "pitch_span_st": 6.0,
                "pitch_std_st": 3.0,
                "pitch_motion_st": 0.4,
                "energy_span_db": 20.0,
                "pause_ratio": 0.2,
            },
        ]
        MODULE.add_expression_scores(rows)
        self.assertGreater(rows[1]["expressiveness_score"], rows[0]["expressiveness_score"])


if __name__ == "__main__":
    unittest.main()
