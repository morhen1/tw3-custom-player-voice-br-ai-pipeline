import importlib.util
import sys
import tempfile
import unittest
import wave
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "executar_omnivoice.py"
SPEC = importlib.util.spec_from_file_location("executar_omnivoice", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_silence(path: Path, duration: float, rate: int = 24000) -> None:
    frames = round(duration * rate)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\x00\x00" * frames)


class DurationNormalizationTests(unittest.TestCase):
    def test_removes_omnivoice_padding_symmetrically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            write_silence(path, 1.20)
            ok, detail = MODULE.normalize_wav_duration(path, 1.0, 0.30, 0.08)
            self.assertTrue(ok, detail)
            duration, channels, rate = MODULE.wav_info(path)
            self.assertAlmostEqual(duration, 1.0, places=5)
            self.assertEqual((channels, rate), (1, 24000))

    def test_adds_only_small_rounding_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            write_silence(path, 0.96)
            ok, detail = MODULE.normalize_wav_duration(path, 1.0, 0.30, 0.08)
            self.assertTrue(ok, detail)
            self.assertAlmostEqual(MODULE.wav_info(path)[0], 1.0, places=5)

    def test_rejects_large_missing_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            write_silence(path, 0.80)
            ok, detail = MODULE.normalize_wav_duration(path, 1.0, 0.30, 0.08)
            self.assertFalse(ok)
            self.assertIn("excede ajuste seguro", detail)


class ParserTests(unittest.TestCase):
    def test_preprocess_prompt_is_explicitly_enabled_by_default(self):
        args = MODULE.build_parser().parse_args(
            ["--jsonl", "input.jsonl", "--output", "output"]
        )
        self.assertTrue(args.preprocess_prompt)

    def test_preprocess_prompt_can_be_disabled_for_diagnostics(self):
        args = MODULE.build_parser().parse_args(
            [
                "--jsonl",
                "input.jsonl",
                "--output",
                "output",
                "--no-preprocess-prompt",
            ]
        )
        self.assertFalse(args.preprocess_prompt)


if __name__ == "__main__":
    unittest.main()
