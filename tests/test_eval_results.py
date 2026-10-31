from datetime import UTC, datetime, timedelta

import pytest

from cueing_bot.evaluate.metrics import evaluate
from cueing_bot.evaluate.results import (
    DatasetInfo,
    EvalRecord,
    compare,
    latest_comparable,
    record_from_dict,
    record_to_dict,
)
from cueing_bot.evaluate.truth import TrackTruth
from cueing_bot.model import Beat, CueType, Estimate, EstimatedCue, Role

BEATS = tuple(Beat(i * 500.0, i % 4 + 1) for i in range(400))
T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def truth(track_id: str, intro: int) -> TrackTruth:
    return TrackTruth(
        track_id,
        "fp",
        BEATS,
        {
            Role.INTRO_END: (intro,),
            Role.INTRO_END_MINUS_2L: (),
            Role.MAIN_HOT: (),
            Role.OUTRO_HOT: (),
        },
    )


def est(track_id: str, intro: int, name: str = "v1") -> Estimate:
    return Estimate(
        track_id, "fp", (EstimatedCue(CueType.MEMORY, intro, Role.INTRO_END),), (), name
    )


def record(
    truths: list[TrackTruth],
    estimates: list[Estimate],
    *,
    at: datetime = T0,
    version: str = "a-v1",
    name: str = "v1",
) -> EvalRecord:
    ev = evaluate(truths, {e.track_id: e for e in estimates})
    return EvalRecord(at, (name,), DatasetInfo("a", version, "", len(truths), {"off_grid": 2}), ev)


def test_record_round_trips_through_dict() -> None:
    r = record([truth("x", 64), truth("y", 32)], [est("x", 64), est("y", 30)])
    back = record_from_dict(record_to_dict(r))
    assert back.dataset == r.dataset
    assert back.created_at == r.created_at
    assert back.evaluation == r.evaluation


def test_record_dict_has_versions_counts_and_no_titles() -> None:
    d = record_to_dict(record([truth("x", 64)], [est("x", 64)]))
    assert d["estimators"] == ["v1"]
    assert d["dataset"]["truth_version"] == "a-v1"
    assert d["dataset"]["n_tracks"] == 1
    assert d["scores"]["m1"]["intro_end"]["same_beat"]["recall"]["value"] == 1.0
    assert set(d["tracks"][0]) == {"track_id", "has_estimate", "needs_review", "stale", "roles"}


def test_compare_lists_improved_and_regressed_tracks_on_common_truths() -> None:
    before = record(
        [truth("x", 64), truth("y", 32), truth("z", 16)],
        [est("x", 64), est("y", 30), est("z", 16)],
    )
    after = record(
        # z は正解が変わった（手動キューを打ち直した）ので比べない。w は新しく増えた曲
        [truth("x", 64), truth("y", 32), truth("z", 20), truth("w", 8)],
        [est("x", 60, "v2"), est("y", 32, "v2"), est("z", 20, "v2"), est("w", 8, "v2")],
        at=T0 + timedelta(hours=1),
        name="v2",
    )
    c = compare(before, after)
    assert c.comparable
    assert c.n_common == 2
    assert c.improved[Role.INTRO_END] == ("y",)
    assert c.regressed[Role.INTRO_END] == ("x",)
    assert c.before is not None and c.after is not None
    assert c.before.roles[Role.INTRO_END].recall().num == 1
    assert c.after.roles[Role.INTRO_END].recall().num == 1


def test_different_truth_versions_are_not_comparable() -> None:
    a = record([truth("x", 64)], [est("x", 64)])
    b = record([truth("x", 64)], [est("x", 64)], version="a-v2", at=T0 + timedelta(hours=1))
    c = compare(a, b)
    assert not c.comparable
    assert "版" in c.reason


def test_latest_comparable_picks_newest_earlier_record_with_same_dataset() -> None:
    old = record([truth("x", 64)], [est("x", 64)], at=T0)
    newer = record([truth("x", 64)], [est("x", 64)], at=T0 + timedelta(hours=1))
    other = record([truth("x", 64)], [est("x", 64)], at=T0 + timedelta(hours=2), version="a-v2")
    current = record([truth("x", 64)], [est("x", 64)], at=T0 + timedelta(hours=3))
    assert latest_comparable([old, newer, other, current], current) is newer
    assert latest_comparable([current], current) is None


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="タイムゾーン"):
        EvalRecord(
            datetime(2026, 11, 1), ("v1",), DatasetInfo("a", "a-v1", "", 0), evaluate([], {})
        )
