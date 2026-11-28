"""The symptom vocabulary: one list for the CLI, the web form and the API.

The point of these tests is not the word list. It is that severity stays on the 0-3 scale,
that description is separate from measurement, and that a bad id is rejected rather than
stored and silently ignored.
"""

from __future__ import annotations

import pytest

from strength_coach.domain.symptom_vocabulary import (
    SymptomVocabulary,
    SymptomVocabularyError,
)


def test_the_shipped_vocabulary_covers_the_configured_categories():
    vocabulary = SymptomVocabulary.load()
    assert len(vocabulary.characters) == 13
    assert vocabulary.side_ids == ("left", "right", "bilateral", "central")
    # Bands describe the existing 0-3 scale; they are not a new severity scale.
    assert [band.level for band in vocabulary.severity_bands] == [0, 1, 2, 3]
    assert vocabulary.character_label("muscle_soreness") == "Muscle soreness"
    assert vocabulary.character_label("pain") == "Pain / aching"


def test_characters_are_canonicalised_without_duplicates():
    vocabulary = SymptomVocabulary.load()
    assert vocabulary.validate_characters([" Pain", "stiffness", "pain", ""]) == (
        "pain", "stiffness",
    )
    assert vocabulary.validate_characters(None) == ()


def test_unknown_values_are_rejected_with_the_known_list():
    vocabulary = SymptomVocabulary.load()
    with pytest.raises(SymptomVocabularyError, match="pain, sharp_pain"):
        vocabulary.validate_characters(["clicky"])
    with pytest.raises(SymptomVocabularyError, match="left, right, bilateral, central"):
        vocabulary.validate_side("centre")


def test_side_is_optional():
    vocabulary = SymptomVocabulary.load()
    assert vocabulary.validate_side(None) is None
    assert vocabulary.validate_side("") is None


def test_a_removed_character_still_renders_its_stored_id(tmp_path):
    path = tmp_path / "symptoms.v1.yaml"
    path.write_text(
        "characters:\n"
        "  - {id: pain, label: Pain / aching}\n"
        "sides:\n"
        "  - {id: left, label: Left}\n",
        encoding="utf-8",
    )
    vocabulary = SymptomVocabulary.load(path)
    # History is not rewritten when the file changes; an old id shows as itself.
    assert vocabulary.character_label("tingling") == "tingling"


def test_a_duplicate_id_is_a_config_error(tmp_path):
    path = tmp_path / "symptoms.v1.yaml"
    path.write_text(
        "characters:\n"
        "  - {id: pain, label: One}\n"
        "  - {id: pain, label: Two}\n"
        "sides:\n"
        "  - {id: left, label: Left}\n",
        encoding="utf-8",
    )
    with pytest.raises(SymptomVocabularyError, match="duplicate id"):
        SymptomVocabulary.load(path)


def test_a_vocabulary_without_characters_or_sides_is_refused(tmp_path):
    no_characters = tmp_path / "empty.v1.yaml"
    no_characters.write_text(
        "characters: []\nsides: [{id: left, label: Left}]\n", encoding="utf-8"
    )
    with pytest.raises(SymptomVocabularyError, match="at least one character"):
        SymptomVocabulary.load(no_characters)

    no_sides = tmp_path / "sides.v1.yaml"
    no_sides.write_text(
        "characters: [{id: pain, label: Pain}]\nsides: []\n", encoding="utf-8"
    )
    with pytest.raises(SymptomVocabularyError, match="at least one side"):
        SymptomVocabulary.load(no_sides)


def test_a_missing_file_is_an_error_not_an_empty_vocabulary(tmp_path):
    with pytest.raises(SymptomVocabularyError, match="not found"):
        SymptomVocabulary.load(tmp_path / "absent.v1.yaml")
