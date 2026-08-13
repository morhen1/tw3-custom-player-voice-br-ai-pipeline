from __future__ import annotations

import unittest

from preparar_referencias_expressivas_piloto import CANDIDATES, build_config


class BuildConfigTests(unittest.TestCase):
    def test_config_enables_all_seven_styles(self) -> None:
        config = build_config("trabalho/referencias_expressivas_piloto")
        self.assertEqual(config.count("enabled = true"), 7)
        for style in CANDIDATES:
            self.assertIn(f"[referencias.{style}]", config)
            self.assertIn(f"{style}.wav", config)
        self.assertIn("preprocess_prompt = true", config)


if __name__ == "__main__":
    unittest.main()
