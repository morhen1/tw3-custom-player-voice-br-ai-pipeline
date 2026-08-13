from __future__ import annotations

import unittest

from atribuir_estilos_falas_oficiais import assign_style


def row(text: str, markers: str, duration: str = "2.0") -> dict[str, str]:
    return {
        "texto_atual": text,
        "duracao_audio_s": duration,
        "classe_ritmo": "normal",
        "classe_intensidade": "media",
        "classe_pausas": "pausa_leve",
        "marcadores_texto": markers,
    }


class AssignStyleTests(unittest.TestCase):
    def test_detects_investigation_before_generic_question(self) -> None:
        style, confidence, _ = assign_style(
            row("As cavernas estão tranquilas agora?", "pergunta")
        )
        self.assertEqual(style, "investigacao_observacional")
        self.assertEqual(confidence, "alta")

    def test_detects_short_alert(self) -> None:
        style, confidence, _ = assign_style(row("O que foi?", "pergunta", "0.25"))
        self.assertEqual(style, "alerta_tenso")
        self.assertEqual(confidence, "media")

    def test_detects_irony(self) -> None:
        style, confidence, _ = assign_style(
            row("Astúcia? E você acha isso digno de um cavaleiro?", "pergunta")
        )
        self.assertEqual(style, "ironia_seca")
        self.assertEqual(confidence, "alta")

    def test_long_reasoning_has_narrative_priority(self) -> None:
        text = " ".join(["palavra"] * 25)
        style, confidence, _ = assign_style(row(text, "declarativa", "9.0"))
        self.assertEqual(style, "narrativa_contida")
        self.assertEqual(confidence, "alta")


if __name__ == "__main__":
    unittest.main()
