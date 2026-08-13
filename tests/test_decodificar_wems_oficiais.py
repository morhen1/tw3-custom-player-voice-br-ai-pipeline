from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from decodificar_wems_oficiais import validate_pcm_wav


class DecodeOfficialWemsTests(unittest.TestCase):
    def test_validates_pcm_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.wav"
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(48_000)
                handle.writeframes(bytes(9_600))

            duration, channels, rate, bits = validate_pcm_wav(path)

            self.assertAlmostEqual(duration, 0.1, places=6)
            self.assertEqual(channels, 1)
            self.assertEqual(rate, 48_000)
            self.assertEqual(bits, 16)


if __name__ == "__main__":
    unittest.main()
