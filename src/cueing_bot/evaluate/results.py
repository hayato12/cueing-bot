"""評価の結果の記録と、前回との比べ方（S1「結果を日付付きで保存し、前回と比べられる」）。

記録には曲の ID だけを入れ、曲名は入れない。それでも個人のライブラリから作ったものなので、置き場は
リポジトリの外の data フォルダ（architecture.md 4 章）。リポジトリに残すのは集計の数字だけ（D3）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cueing_bot.evaluate.metrics import (
    Evaluation,
    Level,
    Ratio,
    RoleOutcome,
    Scores,
    TrackOutcome,
    score,
)
from cueing_bot.model import MVP_ROLES, Role

SCHEMA_VERSION = 1
"""記録の JSON の形の版。形を変えたら上げる。"""


@dataclass(frozen=True)
class DatasetInfo:
    """評価データの版。これが違う記録どうしは比べられない（評価データの版・曲数を残す）。"""

    kind: str
    """`a`（手動キューから自動）、`b-dev`（開発用）、`b-holdout`（判定用）。"""
    truth_version: str
    """正解の取り出し方の版（`truth.TRUTH_VERSION`）。b では b の読み込み方の版。"""
    source_hash: str
    """b の CSV のハッシュ。a では空。"""
    n_tracks: int
    excluded: Mapping[str, int] = field(default_factory=dict[str, int])
    """外した曲の数（理由ごと）。"""


@dataclass(frozen=True)
class EvalRecord:
    created_at: datetime
    estimators: tuple[str, ...]
    """評価した推定の名前と版。ふつうは 1 つ。"""
    dataset: DatasetInfo
    evaluation: Evaluation


# --- JSON に直す -----------------------------------------------------------------


def _ratio(r: Ratio) -> dict[str, Any]:
    return {"num": r.num, "den": r.den, "value": r.value}


def scores_to_dict(s: Scores) -> dict[str, Any]:
    return {
        "n_tracks": s.n_tracks,
        "n_missing_estimate": s.n_missing_estimate,
        "m1": {
            role.value: {
                "n_tracks": rs.n_tracks,
                "n_estimated": rs.n_estimated,
                "n_truth": rs.n_truth,
                "none_tracks": rs.none_tracks,
                "none_correct": rs.none_correct,
                **{
                    lv.value: {
                        "hits": rs.hits[lv],
                        "precision": _ratio(rs.precision(lv)),
                        "recall": _ratio(rs.recall(lv)),
                    }
                    for lv in Level
                },
            }
            for role, rs in s.roles.items()
        },
        "m2": _ratio(s.m2),
        "m3": _ratio(s.m3),
        "m4": _ratio(s.m4),
    }


def _outcome_to_dict(t: TrackOutcome) -> dict[str, Any]:
    return {
        "track_id": t.track_id,
        "has_estimate": t.has_estimate,
        "needs_review": t.needs_review,
        "roles": {
            role.value: {
                "truth": list(o.truth),
                "estimated": list(o.estimated),
                "hits": {lv.value: o.hits[lv] for lv in Level},
                "diffs": list(o.diffs),
            }
            for role, o in t.roles.items()
        },
    }


def _outcome_from_dict(d: Mapping[str, Any]) -> TrackOutcome:
    roles: dict[Role, RoleOutcome] = {}
    for name, o in d["roles"].items():
        roles[Role(name)] = RoleOutcome(
            truth=tuple(int(x) for x in o["truth"]),
            estimated=tuple(int(x) for x in o["estimated"]),
            hits={lv: int(o["hits"][lv.value]) for lv in Level},
            diffs=tuple(int(x) for x in o["diffs"]),
        )
    return TrackOutcome(
        track_id=str(d["track_id"]),
        roles=roles,
        has_estimate=bool(d["has_estimate"]),
        needs_review=bool(d["needs_review"]),
    )


def record_to_dict(r: EvalRecord) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": r.created_at.isoformat(timespec="seconds"),
        "estimators": list(r.estimators),
        "dataset": {
            "kind": r.dataset.kind,
            "truth_version": r.dataset.truth_version,
            "source_hash": r.dataset.source_hash,
            "n_tracks": r.dataset.n_tracks,
            "excluded": dict(r.dataset.excluded),
        },
        # 読みやすさのために集計も書く。読み込むときは曲ごとの結果から計算し直す
        "scores": scores_to_dict(r.evaluation.scores),
        "tracks": [_outcome_to_dict(t) for t in r.evaluation.tracks],
    }


def record_from_dict(d: Mapping[str, Any]) -> EvalRecord:
    if d.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"記録の形の版が違います：{d.get('schema_version')}")
    ds = d["dataset"]
    tracks = tuple(_outcome_from_dict(t) for t in d["tracks"])
    return EvalRecord(
        created_at=datetime.fromisoformat(str(d["created_at"])),
        estimators=tuple(str(e) for e in d["estimators"]),
        dataset=DatasetInfo(
            kind=str(ds["kind"]),
            truth_version=str(ds["truth_version"]),
            source_hash=str(ds["source_hash"]),
            n_tracks=int(ds["n_tracks"]),
            excluded={str(k): int(v) for k, v in ds["excluded"].items()},
        ),
        evaluation=Evaluation(tracks, score(tracks)),
    )


# --- 前回と比べる ----------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """2 つの記録を、同じ曲・同じ正解の範囲で比べた結果。"""

    comparable: bool
    reason: str
    """比べられないときの理由。"""
    n_common: int = 0
    """両方にあり、正解も同じだった曲の数。"""
    before: Scores | None = None
    after: Scores | None = None
    improved: Mapping[Role, tuple[str, ...]] = field(default_factory=dict[Role, tuple[str, ...]])
    """役割ごとに、前は外れて今回は当たった曲の ID。"""
    regressed: Mapping[Role, tuple[str, ...]] = field(default_factory=dict[Role, tuple[str, ...]])
    """役割ごとに、前は当たって今回は外れた曲の ID。"""


def comparable(before: DatasetInfo, after: DatasetInfo) -> str | None:
    """比べられなければ理由を返す。"""
    if before.kind != after.kind:
        return f"評価データの種類が違います（{before.kind} と {after.kind}）"
    if before.truth_version != after.truth_version:
        return f"正解の取り出し方の版が違います（{before.truth_version} と {after.truth_version}）"
    if before.source_hash != after.source_hash:
        return "評価データ b のファイルが変わっています"
    return None


def _truths(t: TrackOutcome) -> dict[Role, tuple[int, ...]]:
    return {role: o.truth for role, o in t.roles.items()}


def compare(before: EvalRecord, after: EvalRecord) -> Comparison:
    """同じ曲で前後を比べる（requirements.md 1 章「同じ曲で前後のどちらが当たったかを比べる」）。

    評価データ a は、手動キューを打った曲が増えると中身が変わる。そこで、両方にあって正解も同じ曲だけで
    比べる。
    """
    reason = comparable(before.dataset, after.dataset)
    if reason is not None:
        return Comparison(False, reason)
    prev = {t.track_id: t for t in before.evaluation.tracks}
    common_before: list[TrackOutcome] = []
    common_after: list[TrackOutcome] = []
    for t in after.evaluation.tracks:
        p = prev.get(t.track_id)
        if p is not None and _truths(p) == _truths(t):
            common_before.append(p)
            common_after.append(t)
    if not common_after:
        return Comparison(False, "同じ正解の曲が 1 曲もありません")

    improved: dict[Role, tuple[str, ...]] = {}
    regressed: dict[Role, tuple[str, ...]] = {}
    for role in MVP_ROLES:
        up: list[str] = []
        down: list[str] = []
        for p, t in zip(common_before, common_after, strict=True):
            if role not in t.roles:
                continue
            was, now = p.roles[role].exact, t.roles[role].exact
            if now and not was:
                up.append(t.track_id)
            elif was and not now:
                down.append(t.track_id)
        improved[role] = tuple(up)
        regressed[role] = tuple(down)
    return Comparison(
        True,
        "",
        n_common=len(common_after),
        before=score(common_before),
        after=score(common_after),
        improved=improved,
        regressed=regressed,
    )


def latest_comparable(records: Sequence[EvalRecord], current: EvalRecord) -> EvalRecord | None:
    """`current` より前の記録のうち、評価データの版が同じで一番新しいもの。"""
    candidates = [
        r
        for r in records
        if r.created_at < current.created_at and comparable(r.dataset, current.dataset) is None
    ]
    return max(candidates, key=lambda r: r.created_at, default=None)
