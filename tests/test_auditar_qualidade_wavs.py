from __future__ import annotations

import importlib.util
import math
import struct
import sys
import tempfile
import unittest
import wave
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "auditar_qualidade_wavs.py"
SPEC = importlib.util.spec_from_file_location("auditar_qualidade_wavs", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_pattern(path: Path, pattern: list[tuple[float, float]], rate: int = 16000) -> None:
    samples: list[int] = []
    phase = 0
    for duration_s, amplitude in pattern:
        count = int(round(duration_s * rate))
        for _ in range(count):
            value = amplitude * math.sin(2.0 * math.pi * 220.0 * phase / rate)
            samples.append(int(max(-1.0, min(1.0, value)) * 32767))
            phase += 1
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class QualityAuditTests(unittest.TestCase):
    def test_detects_clustered_internal_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cluster.wav"
            pattern: list[tuple[float, float]] = [(0.20, 0.0)]
            for _ in range(5):
                pattern.extend([(0.18, 0.3), (0.08, 0.0)])
            pattern.extend([(0.18, 0.3), (0.10, 0.0)])
            write_pattern(path, pattern)
            metrics = MODULE.analyze_wav(path)
            self.assertGreaterEqual(metrics.micro_pause_count, 4)

    def test_detects_short_tail_island(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tail.wav"
            write_pattern(
                path,
                [
                    (0.10, 0.0),
                    (0.80, 0.3),
                    (0.10, 0.0),
                    (0.08, 0.3),
                    (0.10, 0.0),
                ],
            )
            metrics = MODULE.analyze_wav(path)
            self.assertGreater(metrics.tail_island_ms, 0.0)
            self.assertLessEqual(metrics.tail_island_ms, 100.0)

    def test_text_metrics_ignore_terminal_question_mark(self) -> None:
        metrics = MODULE.text_metrics("Alguém viu o que aconteceu?")
        self.assertEqual(metrics["words"], 5)
        self.assertEqual(metrics["internal_punctuation"], 0)
        self.assertGreaterEqual(metrics["syllables"], 5)

    def test_reads_selection_ids(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "selection.jsonl"
            path.write_text(
                json.dumps({"id": "0x0004fbb0", "text": "Teste"}) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(MODULE.read_selection_ids(path), {"0x0004fbb0"})


if __name__ == "__main__":
    unittest.main()
