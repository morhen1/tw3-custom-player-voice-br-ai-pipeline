from __future__ import annotations

import unittest

from auditar_portugues_falas import clean_vocal_actions, gender_proposal, manual_gender_proposal


class PortugueseAuditTests(unittest.TestCase):
    def test_removes_stage_direction_but_keeps_speech(self) -> None:
        text, notes = clean_vocal_actions("*Suspira* Está bem. Vamos.")
        self.assertEqual(text, "Está bem. Vamos.")
        self.assertTrue(notes)

    def test_removes_argh_without_dropping_sentence(self) -> None:
        text, _ = clean_vocal_actions("Argh. Vou começar de novo.")
        self.assertEqual(text, "Vou começar de novo.")

    def test_preserves_unrelated_lowercase_after_ellipsis(self) -> None:
        text, _ = clean_vocal_actions("Argh. Sonhei primeiro... depois, só pesadelos.")
        self.assertEqual(text, "Sonhei primeiro... depois, só pesadelos.")

    def test_removes_drawn_out_argh_without_orphan_punctuation(self) -> None:
        text, _ = clean_vocal_actions("Aaa-argh! Agora corra.")
        self.assertEqual(text, "Agora corra.")

    def test_pure_argh_becomes_empty(self) -> None:
        text, _ = clean_vocal_actions("Argh!")
        self.assertEqual(text, "")

    def test_removes_ugh_cough_and_tsc(self) -> None:
        text, notes = clean_vocal_actions("Ugh. Cof! Tsc. Vamos.")
        self.assertEqual(text, "Vamos.")
        self.assertTrue(notes)

    def test_repairs_internal_punctuation_and_capitalization(self) -> None:
        text, _ = clean_vocal_actions(
            "Jarro vazio. Cof. Agh, muito forte. Droga. Argh, tudo bem."
        )
        self.assertEqual(text, "Jarro vazio. Muito forte. Droga. Tudo bem.")

    def test_removes_written_hiss(self) -> None:
        text, _ = clean_vocal_actions("Argh... maldito gato. Ffwsshht!")
        self.assertEqual(text, "Maldito gato.")

    def test_keeps_semantic_smell_verb(self) -> None:
        text, notes = clean_vocal_actions("Algo cheira estranho.")
        self.assertEqual(text, "Algo cheira estranho.")
        self.assertFalse(notes)

    def test_feminizes_explicit_first_person(self) -> None:
        text, notes = gender_proposal("Estou pronto para partir.")
        self.assertEqual(text, "Estou pronta para partir.")
        self.assertTrue(notes)

    def test_feminizes_implied_first_person_after_creio(self) -> None:
        text, notes = gender_proposal("Creio que estava certo em desconfiar.")
        self.assertEqual(text, "Creio que estava certa em desconfiar.")
        self.assertTrue(notes)

    def test_does_not_feminize_other_person(self) -> None:
        text, notes = gender_proposal("Você estava certo em desconfiar.")
        self.assertEqual(text, "Você estava certo em desconfiar.")
        self.assertFalse(notes)

    def test_does_not_feminize_object(self) -> None:
        text, notes = gender_proposal("O cheiro estava fraco.")
        self.assertEqual(text, "O cheiro estava fraco.")
        self.assertFalse(notes)

    def test_applies_context_bound_manual_gender_edit(self) -> None:
        text, notes = manual_gender_proposal(
            "0x00076c93", "Serei pago além disso, certo?"
        )
        self.assertEqual(text, "Serei paga além disso, certo?")
        self.assertTrue(notes)

    def test_manual_gender_edit_changes_article_and_noun(self) -> None:
        text, _ = manual_gender_proposal(
            "0x00119967", "Quando era um garotinho, não me lembro como."
        )
        self.assertEqual(text, "Quando era uma garotinha, não me lembro como.")


if __name__ == "__main__":
    unittest.main()
