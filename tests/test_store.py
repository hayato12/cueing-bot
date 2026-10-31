import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cueing_bot import store
from cueing_bot.evaluate.metrics import evaluate
from cueing_bot.evaluate.results import DatasetInfo, EvalRecord
from cueing_bot.model import CueType, Estimate, EstimatedCue, ReviewReason, Role


def sample_estimate(track_id: str = "1") -> Estimate:
    return Estimate(
        track_id,
        "abc",
        (
            EstimatedCue(CueType.MEMORY, 64, Role.INTRO_END),
            EstimatedCue(CueType.HOT_A, 320, Role.MAIN_HOT, (ReviewReason("c", "理由"),)),
        ),
        (ReviewReason("format_unverified", "形式が未確認"),),
        "rules-v1",
    )


def test_estimates_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "estimates" / "run.json"
    store.save_estimates(path, [sample_estimate("1"), sample_estimate("2")])
    loaded = store.load_estimates(path)
    assert loaded == {"1": sample_estimate("1"), "2": sample_estimate("2")}
    assert not list(path.parent.glob("*.tmp"))


def test_duplicate_estimates_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    store.save_estimates(path, [sample_estimate("1"), sample_estimate("1")])
    with pytest.raises(ValueError, match="2 つ"):
        store.load_estimates(path)


def test_eval_records_are_saved_with_date_and_loaded(tmp_path: Path) -> None:
    at = datetime(2026, 11, 1, 9, 30, 5, tzinfo=UTC)
    rec = EvalRecord(at, ("rules/v1",), DatasetInfo("a", "a-v1", "", 0), evaluate([], {}))
    path = store.save_eval_record(tmp_path, rec)
    assert path.parent == tmp_path
    assert path.name == "20261101-093005-a-rules_v1.json"
    (tmp_path / "broken.json").write_text(json.dumps({"schema_version": 999}))
    loaded = store.load_eval_records(tmp_path)
    assert [r.created_at for r in loaded] == [at]


def test_written_track_ids_reads_all_logs(tmp_path: Path) -> None:
    assert store.written_track_ids(tmp_path / "none") == set()
    (tmp_path / "a.json").write_text(json.dumps({"tracks": [{"track_id": "1"}, {"track_id": 2}]}))
    (tmp_path / "b.json").write_text(json.dumps({"tracks": [{"track_id": "3"}]}))
    assert store.written_track_ids(tmp_path) == {"1", "2", "3"}


def test_unreadable_write_log_is_an_error_not_silently_skipped(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text(json.dumps({"something": []}))
    with pytest.raises(ValueError, match="読めません"):
        store.written_track_ids(tmp_path)
