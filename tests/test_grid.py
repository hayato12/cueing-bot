import pytest

from cueing_bot.library.grid import beats_from_pqtz, fingerprint, phrases_from_pssi
from cueing_bot.model import Beat


def test_beats_from_pqtz_converts_seconds_to_ms() -> None:
    beats = beats_from_pqtz([1, 2, 3, 4, 1], [0.1, 0.6, 1.1, 1.6, 2.1])
    assert beats[0] == Beat(time_ms=100.0, beat_in_bar=1)
    assert beats[4].time_ms == pytest.approx(2100.0)
    assert [b.beat_in_bar for b in beats] == [1, 2, 3, 4, 1]


def test_beats_from_pqtz_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="数が合いません"):
        beats_from_pqtz([1, 2], [0.0])


def test_beats_from_pqtz_rejects_non_increasing_times() -> None:
    with pytest.raises(ValueError, match="増えていません"):
        beats_from_pqtz([1, 2, 3], [0.0, 0.5, 0.5])


def test_phrases_from_pssi_uses_zero_based_index_and_mood_labels() -> None:
    # mood 1（high）：1=Intro、2=Up、5=Chorus
    phrases = phrases_from_pssi(1, [(1, 1), (33, 2), (65, 5)], n_beats=100)
    assert [(p.beat_index, p.label) for p in phrases] == [(0, "Intro"), (32, "Up"), (64, "Chorus")]


def test_phrases_from_pssi_drops_phrases_outside_the_grid_and_sorts() -> None:
    phrases = phrases_from_pssi(2, [(65, 9), (1, 1), (0, 2), (200, 10)], n_beats=100)
    assert [(p.beat_index, p.label) for p in phrases] == [(0, "Intro"), (64, "Chorus")]


def test_phrases_from_pssi_keeps_unknown_kinds() -> None:
    phrases = phrases_from_pssi(1, [(1, 4)], n_beats=10)
    assert phrases[0].label == "kind4"


def test_fingerprint_changes_when_grid_or_file_changes() -> None:
    beats = beats_from_pqtz([1, 2], [0.0, 0.5])
    base = fingerprint("/a.mp3", 100, 1, beats)
    assert base == fingerprint("/a.mp3", 100, 1, beats)
    assert base != fingerprint("/a.mp3", 100, 2, beats)
    assert base != fingerprint("/a.mp3", 101, 1, beats)
    assert base != fingerprint("/a.mp3", 100, 1, beats_from_pqtz([1, 2], [0.0, 0.51]))
