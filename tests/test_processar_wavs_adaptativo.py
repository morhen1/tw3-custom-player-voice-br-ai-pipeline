from __future__ import annotations

import importlib.util
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "processar_wavs_adaptativo.py"
SPEC = importlib.util.spec_from_file_location("processar_wavs_adaptativo", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_tone_with_padding(
    path: Path,
    leading: float,
    tone: float,
    trailing: float,
    rate: int = 24000,
) -> None:
    samples: list[int] = []
    samples.extend([0] * round(leading * rate))
    for index in range(round(tone * rate)):
        samples.append(round(8000 * math.sin(2 * math.pi * 220 * index / rate)))
    samples.extend([0] * round(trailing * rate))
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class EdgeDetectionTests(unittest.TestCase):
    def test_detects_padding_without_scanning_silence_as_voice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            write_tone_with_padding(path, 0.30, 1.0, 0.70)
            edges = MODULE.detect_voice_edges(path, -45.0, 20.0, 80.0)
            self.assertAlmostEqual(edges.raw_duration, 2.0, places=3)
            self.assertGreaterEqual(edges.trim_start, 0.18)
            self.assertLessEqual(edges.trim_start, 0.24)
            self.assertGreaterEqual(edges.trim_end, 1.36)
            self.assertLessEqual(edges.trim_end, 1.42)


class DurationPlanTests(unittest.TestCase):
    def test_applies_only_speed_needed_for_allowed_overage(self) -> None:
        plan = MODULE.plan_duration(3.635833, 4.934503, 15.0, 1.20, 0.80)
        self.assertLess(plan.projected_delta_pct, 15.0)
        self.assertGreater(plan.projected_delta_pct, 14.0)
        self.assertGreater(plan.speed, 1.17)
        self.assertLess(plan.speed, 1.20)
        self.assertEqual(plan.status, "ok")

    def test_flags_line_still_long_at_speed_cap(self) -> None:
        plan = MODULE.plan_duration(3.0, 5.0, 15.0, 1.20, 0.80)
        self.assertEqual(plan.speed, 1.20)
        self.assertEqual(plan.status, "revisar_longa")

    def test_flags_suspiciously_short_line(self) -> None:
        plan = MODULE.plan_duration(2.0, 1.0, 15.0, 1.20, 0.80)
        self.assertEqual(plan.status, "revisar_curta")

    def test_short_original_uses_absolute_tolerance(self) -> None:
        plan = MODULE.plan_duration(0.255566, 0.840000)
        self.assertEqual(plan.status, "ok")
        self.assertEqual(plan.speed, 1.20)

    def test_filter_never_reintroduces_makeup_two(self) -> None:
        edges = MODULE.EdgeInfo(2.0, 0.2, 1.8, 0.12, 1.88)
        plan = MODULE.DurationPlan(1.1, 1.6, 10.0, "ok")
        filter_text = MODULE.build_filter(edges, plan, -23.0)
        self.assertIn("atempo=1.100000", filter_text)
        self.assertIn("makeup=1", filter_text)
        self.assertNotIn("makeup=2", filter_text)
        self.assertIn("loudnorm=I=-23", filter_text)

    def test_duration_difference_is_advisory_by_default(self) -> None:
        short_status, _ = MODULE.classify_final(2.0, 1.0, 15.0, 0.60, 0.50)
        long_status, _ = MODULE.classify_final(3.0, 5.0, 15.0, 0.60, 0.50)
        self.assertEqual(short_status, "aviso_curta")
        self.assertEqual(long_status, "aviso_longa")

    def test_strict_duration_audit_still_blocks(self) -> None:
        short_status, _ = MODULE.classify_final(
            2.0, 1.0, 15.0, 0.60, 0.50, "strict"
        )
        long_status, _ = MODULE.classify_final(
            3.0, 5.0, 15.0, 0.60, 0.50, "strict"
        )
        self.assertEqual(short_status, "revisar_curta")
        self.assertEqual(long_status, "revisar_longa")


if __name__ == "__main__":
    unittest.main()
