from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    import torch
except ImportError:  # pragma: no cover - ambiente mínimo sem OmniVoice
    torch = None


MODULE_PATH = Path(__file__).resolve().parents[1] / "voice_clone_prompt_io.py"
SPEC = importlib.util.spec_from_file_location("voice_clone_prompt_io", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@unittest.skipIf(torch is None, "PyTorch não instalado")
class VoicePromptIOTests(unittest.TestCase):
    def test_round_trip_safe_payload(self) -> None:
        prompt = SimpleNamespace(
            ref_audio_tokens=torch.arange(24).reshape(3, 8),
            ref_text="Texto de referência.",
            ref_rms=0.125,
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "prompt.pt"
            MODULE.save_voice_clone_prompt(
                prompt,
                output,
                preprocess_prompt=True,
                metadata={"style": "investigacao"},
            )
            payload = MODULE.load_prompt_payload(output)
        self.assertTrue(payload["preprocess_prompt"])
        self.assertEqual(payload["ref_text"], "Texto de referência.")
        self.assertEqual(payload["metadata"]["style"], "investigacao")
        self.assertTrue(torch.equal(payload["ref_audio_tokens"], prompt.ref_audio_tokens))


if __name__ == "__main__":
    unittest.main()
