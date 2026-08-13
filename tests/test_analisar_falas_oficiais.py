from __future__ import annotations

import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from analisar_falas_oficiais import pause_intervals


class AnalyzeOfficialSpeechTests(unittest.TestCase):
    def test_detects_internal_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.wav"
            rate = 48_000
            samples: list[int] = []
            samples.extend([0] * int(rate * 0.05))
            for index in range(int(rate * 0.20)):
                samples.append(int(12_000 * math.sin(2 * math.pi * 220 * index / rate)))
            samples.extend([0] * int(rate * 0.10))
            for index in range(int(rate * 0.20)):
                samples.append(int(12_000 * math.sin(2 * math.pi * 220 * index / rate)))
            samples.extend([0] * int(rate * 0.05))
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))

            intervals = pause_intervals(path)

            self.assertEqual(len(intervals), 1)
            self.assertAlmostEqual(intervals[0].duration_ms, 100.0, delta=20.0)


if __name__ == "__main__":
    unittest.main()
