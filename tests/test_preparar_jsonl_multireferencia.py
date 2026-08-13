from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "preparar_jsonl_multireferencia.py"
SPEC = importlib.util.spec_from_file_location(
    "preparar_jsonl_multireferencia", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class MultiReferenceTests(unittest.TestCase):
    def test_loads_enabled_default_and_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "voice.wav").write_bytes(b"RIFF")
            (root / "voice.txt").write_text("Texto exato.", encoding="utf-8")
            (root / "voice.pt").write_bytes(b"prompt")
            config = root / "voices.toml"
            config.write_text(
                """
[estilos]
padrao = "investigacao"
[referencias.investigacao]
enabled = true
ref_audio = "voice.wav"
ref_text_file = "voice.txt"
prompt = "voice.pt"
preprocess_prompt = true
""".strip(),
                encoding="utf-8",
            )
            default, references = MODULE.load_config(config)
            assignments_file = root / "assignments.csv"
            assignments_file.write_text(
                "id_hex;estilo\n0x00000001;investigacao\n",
                encoding="utf-8",
            )
            assignments = MODULE.read_assignments(assignments_file)
        self.assertEqual(default, "investigacao")
        self.assertTrue(references[default].enabled)
        self.assertTrue(references[default].preprocess_prompt)
        self.assertEqual(assignments["0x00000001"], "investigacao")


if __name__ == "__main__":
    unittest.main()
