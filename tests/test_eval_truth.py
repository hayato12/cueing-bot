import pytest

from cueing_bot.evaluate.beats import bar_numbers, bar_start_beat, bpm, l_bars, nearest_beat
from cueing_bot.evaluate.truth import (
    Excluded,
    ExcludeReason,
    Extracted,
    RoleExcludeReason,
    build_dataset_a,
    extract_truth,
)
from cueing_bot.model import Beat, CueType, ExistingCue, ExistingCues, Role


def grid(n_bars: int, tempo: float = 128.0, *, pickup: int = 0) -> tuple[Beat, ...]:
    """作り物のグリッド。`pickup` 拍だけ、小節の 1 拍目より前の拍を置く。"""
    step = 60_000.0 / tempo
    n = pickup + n_bars * 4
    first = (4 - pickup) % 4 + 1  # pickup=1 なら 4 拍目から始まる
    return tuple(Beat(i * step, (first - 1 + i) % 4 + 1) for i in range(n))


def at_bar(beats: tuple[Beat, ...], bar: int, offset_ms: float = 0.0) -> int:
    """小節の 1 拍目の時刻（ms、整数）。手動キューの `InMsec` の代わり。"""
    index = bar_start_beat(beats, bar)
    assert index is not None
    return round(beats[index].time_ms + offset_ms)


def cues(track_id: str, items: list[tuple[CueType | int, int]]) -> ExistingCues:
    return ExistingCues(track_id, tuple(ExistingCue(int(k), t, False) for k, t in items))


def extracted(result: Extracted | Excluded) -> Extracted:
    assert isinstance(result, Extracted), result
    return result


# --- beats ----------------------------------------------------------------------


def test_nearest_beat_returns_index_and_signed_offset() -> None:
    beats = grid(2, 120.0)  # 500 ms ごと
    assert nearest_beat(beats, 520.0) == (1, 20.0)
    assert nearest_beat(beats, 740.0) == (1, 240.0)
    assert nearest_beat(beats, 760.0) == (2, -240.0)
    assert nearest_beat(beats, -50.0) == (0, -50.0)
    assert nearest_beat(beats, 99_999.0)[0] == len(beats) - 1


def test_bar_numbers_put_pickup_beats_in_bar_zero() -> None:
    beats = grid(2, pickup=1)
    assert beats[0].beat_in_bar == 4
    assert bar_numbers(beats) == (0, 1, 1, 1, 1, 2, 2, 2, 2)
    assert bar_start_beat(beats, 1) == 1
    assert bar_start_beat(beats, 3) is None


def test_l_is_four_bars_up_to_120_bpm_and_eight_above() -> None:
    assert l_bars(bpm(grid(4, 120.0))) == 4
    assert l_bars(119.9) == 4
    assert l_bars(120.004) == 4  # 小数 2 桁で 120.00
    assert l_bars(120.01) == 8
    assert l_bars(bpm(grid(4, 128.0))) == 8


# --- extract_truth --------------------------------------------------------------


def test_extracts_four_roles_from_a_typical_house_track() -> None:
    # cueing-theory.md 3.2 の例（BPM 124 相当、L=8 小節、2L=16 小節）
    beats = grid(160, 124.0)
    result = extracted(
        extract_truth(
            cues(
                "t1",
                [
                    (CueType.MEMORY, at_bar(beats, 1)),
                    (CueType.MEMORY, at_bar(beats, 9)),
                    (CueType.MEMORY, at_bar(beats, 17)),  # A メロの頭
                    (
                        CueType.MEMORY,
                        at_bar(beats, 49),
                    ),  # 抜け（間が 32 小節なのでイントロではない）
                    (CueType.HOT_A, at_bar(beats, 81)),
                    (CueType.HOT_B, at_bar(beats, 129)),
                    (CueType.HOT_H, at_bar(beats, 145)),
                ],
            ),
            beats,
            "fp",
        )
    )

    def beat(bar: int) -> int:  # ピックアップのないグリッドでの小節の頭
        return (bar - 1) * 4

    assert result.truth.roles == {
        Role.INTRO_END: (beat(17),),
        Role.INTRO_END_MINUS_2L: (beat(1),),
        Role.MAIN_HOT: (beat(81), beat(129)),
        Role.OUTRO_HOT: (beat(145),),
    }
    assert result.role_excluded == {}


def test_short_intro_has_no_minus_2l_and_missing_hot_cues_mean_none() -> None:
    beats = grid(64, 100.0)  # L=4、2L=8 小節
    result = extracted(
        extract_truth(
            cues("t", [(CueType.MEMORY, at_bar(beats, 1)), (CueType.MEMORY, at_bar(beats, 5))]),
            beats,
            "fp",
        )
    )
    assert result.truth.roles == {
        Role.INTRO_END: (16,),
        Role.INTRO_END_MINUS_2L: (),
        Role.MAIN_HOT: (),
        Role.OUTRO_HOT: (),
    }


def test_long_intro_without_minus_2l_cue_excludes_only_that_role() -> None:
    beats = grid(64, 128.0)  # 2L=16 小節
    result = extracted(
        extract_truth(
            cues(
                "t",
                [
                    (CueType.MEMORY, at_bar(beats, 1)),
                    (CueType.MEMORY, at_bar(beats, 13)),
                    (CueType.MEMORY, at_bar(beats, 25)),  # 2L 前（9 小節目）には打っていない
                ],
            ),
            beats,
            "fp",
        )
    )
    assert Role.INTRO_END_MINUS_2L not in result.truth.roles
    assert result.truth.roles[Role.INTRO_END] == (96,)
    assert result.role_excluded == {Role.INTRO_END_MINUS_2L: RoleExcludeReason.MINUS_2L_NOT_CUED}


def test_cues_are_snapped_within_tolerance_and_far_ones_exclude_the_track() -> None:
    beats = grid(32, 100.0)
    near = cues(
        "t",
        [(CueType.MEMORY, at_bar(beats, 1, 20.0)), (CueType.MEMORY, at_bar(beats, 5, -20.0))],
    )
    assert extracted(extract_truth(near, beats, "fp")).truth.roles[Role.INTRO_END] == (16,)

    far = cues("t", [(CueType.MEMORY, at_bar(beats, 1)), (CueType.MEMORY, at_bar(beats, 5, 50.0))])
    result = extract_truth(far, beats, "fp")
    assert isinstance(result, Excluded)
    assert result.reason == ExcludeReason.OFF_GRID
    assert isinstance(extract_truth(far, beats, "fp", snap_tolerance_ms=60.0), Extracted)


def test_loops_and_unknown_kinds_are_ignored() -> None:
    beats = grid(32, 100.0)
    track = ExistingCues(
        "t",
        (
            ExistingCue(CueType.MEMORY, at_bar(beats, 1), False),
            ExistingCue(CueType.MEMORY, at_bar(beats, 5), False),
            ExistingCue(CueType.MEMORY, at_bar(beats, 9), True),  # ループ
            ExistingCue(4, at_bar(beats, 13), False),  # 知らない Kind
        ),
    )
    roles = extracted(extract_truth(track, beats, "fp")).truth.roles
    assert roles[Role.INTRO_END] == (16,)


def test_tracks_with_fewer_than_two_memory_cues_are_excluded() -> None:
    beats = grid(32)
    result = extract_truth(
        cues("t", [(CueType.MEMORY, 0), (CueType.HOT_A, at_bar(beats, 9))]), beats, "fp"
    )
    assert isinstance(result, Excluded)
    assert result.reason == ExcludeReason.TOO_FEW_MEMORY_CUES


def test_build_dataset_a_drops_tracks_written_by_the_app_and_counts_reasons() -> None:
    beats = grid(64, 128.0)
    good = cues("good", [(CueType.MEMORY, at_bar(beats, 1)), (CueType.MEMORY, at_bar(beats, 17))])
    no_2l = cues(
        "no2l",
        [
            (CueType.MEMORY, at_bar(beats, 1)),
            (CueType.MEMORY, at_bar(beats, 13)),
            (CueType.MEMORY, at_bar(beats, 25)),
        ],
    )
    written = cues("written", [(CueType.MEMORY, 0), (CueType.MEMORY, at_bar(beats, 17))])
    few = cues("few", [(CueType.MEMORY, 0)])
    data = build_dataset_a(
        [(good, beats, "fp"), (no_2l, beats, "fp"), (written, beats, "fp"), (few, beats, "fp")],
        written_by_app={"written"},
    )
    assert [t.track_id for t in data.truths] == ["good", "no2l"]
    assert data.excluded_counts() == {
        "written_by_app": 1,
        "too_few_memory_cues": 1,
        "intro_end_minus_2l:minus_2l_not_cued": 1,
    }


def test_truth_keeps_the_fingerprint_of_the_grid() -> None:
    beats = grid(32, 100.0)
    track = cues("t", [(CueType.MEMORY, 0), (CueType.MEMORY, at_bar(beats, 5))])
    assert extracted(extract_truth(track, beats, "abc")).truth.fingerprint == "abc"


@pytest.mark.parametrize("n_beats", [0, 1])
def test_too_short_grid_is_excluded(n_beats: int) -> None:
    beats = grid(1)[:n_beats]
    result = extract_truth(cues("t", [(CueType.MEMORY, 0), (CueType.MEMORY, 10)]), beats, "fp")
    assert isinstance(result, Excluded)
    assert result.reason == ExcludeReason.NO_GRID
