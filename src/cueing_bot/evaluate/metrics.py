"""推定と正解を比べて M1〜M4 を出す（requirements.md 1 章）。

- M1：役割ごとの precision（出したもののうち当たり）と recall（正解のうち当たり）。当たりは同じ拍。
  参考に「同じ小節」と「±1 小節以内」も出す。正解が「ない」曲は別に数える
- M2：4 つの役割が全部当たり、余計なキューもない曲の割合
- M3：要確認を付けなかった曲のうち、M2 の意味で全部当たった曲の割合
- M4：要確認を付けた曲の割合
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from cueing_bot.evaluate.beats import BEATS_PER_BAR, bar_numbers
from cueing_bot.evaluate.truth import TrackTruth
from cueing_bot.model import MVP_ROLES, Estimate, Role


class Level(StrEnum):
    """当たりの基準。M1〜M3 の目標に使うのは `SAME_BEAT` だけで、ほかは参考。"""

    SAME_BEAT = "same_beat"
    SAME_BAR = "same_bar"
    WITHIN_1_BAR = "within_1_bar"
    """ずれが 4 拍以内（スパイク 2 と同じ数え方）。"""


@dataclass(frozen=True)
class Ratio:
    num: int
    den: int

    @property
    def value(self) -> float | None:
        """割合。分母が 0 なら None（「0%」と区別するため）。"""
        return self.num / self.den if self.den else None


@dataclass(frozen=True)
class RoleOutcome:
    """1 曲・1 役割の比べた結果。"""

    truth: tuple[int, ...]
    estimated: tuple[int, ...]
    hits: Mapping[Level, int]
    diffs: tuple[int, ...]
    """組にした推定と正解のずれ（拍。推定が後ろなら正）。ずれの内訳を見るため。"""

    @property
    def exact(self) -> bool:
        """推定が正解とちょうど同じ（数も位置も）。正解が「ない」ときは、推定も出していなければ True。"""
        return self.estimated == self.truth


@dataclass(frozen=True)
class TrackOutcome:
    track_id: str
    roles: Mapping[Role, RoleOutcome]
    """評価した役割だけ。正解が分からない役割は入らない。"""
    has_estimate: bool
    needs_review: bool
    """要確認が付いたか。推定がない曲（推定に失敗した曲）は、全部人がやるので要確認と数える。"""

    @property
    def all_roles_known(self) -> bool:
        return all(r in self.roles for r in MVP_ROLES)

    @property
    def all_correct(self) -> bool | None:
        """M2 の意味で全部当たったか。役割が 1 つでも分からない曲は None（M2 の分母から外す）。"""
        if not self.all_roles_known:
            return None
        return all(o.exact for o in self.roles.values())


@dataclass(frozen=True)
class RoleScore:
    """1 役割の M1。"""

    n_tracks: int
    """この役割を評価した曲の数。"""
    n_estimated: int
    n_truth: int
    hits: Mapping[Level, int]
    none_tracks: int
    """正解が「ない」曲の数。"""
    none_correct: int
    """正解が「ない」曲のうち、推定も出さなかった曲の数（「出さずに当たり」）。"""

    def precision(self, level: Level = Level.SAME_BEAT) -> Ratio:
        return Ratio(self.hits[level], self.n_estimated)

    def recall(self, level: Level = Level.SAME_BEAT) -> Ratio:
        return Ratio(self.hits[level], self.n_truth)


@dataclass(frozen=True)
class Scores:
    roles: Mapping[Role, RoleScore]
    m2: Ratio
    m3: Ratio
    m4: Ratio
    n_tracks: int
    n_missing_estimate: int
    """推定がなかった曲の数。推定を出さなかった（全部外れ）として数えている。"""


@dataclass(frozen=True)
class Evaluation:
    tracks: tuple[TrackOutcome, ...]
    scores: Scores


def _pair(estimated: Sequence[int], truth: Sequence[int]) -> list[tuple[int, int]]:
    """推定と正解を 1 対 1 で組にする。ずれの小さい組から順に取る。"""
    candidates = sorted(
        (abs(e - t), ei, ti) for ei, e in enumerate(estimated) for ti, t in enumerate(truth)
    )
    used_e: set[int] = set()
    used_t: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, ei, ti in candidates:
        if ei in used_e or ti in used_t:
            continue
        used_e.add(ei)
        used_t.add(ti)
        pairs.append((estimated[ei], truth[ti]))
    return pairs


def compare_role(
    estimated: Sequence[int], truth: Sequence[int], bars: Sequence[int]
) -> RoleOutcome:
    """1 曲・1 役割の推定と正解を比べる。`bars` は拍ごとの小節番号。"""
    est = tuple(sorted(estimated))
    tru = tuple(sorted(truth))
    hits = dict.fromkeys(Level, 0)
    diffs: list[int] = []
    for e, t in _pair(est, tru):
        d = e - t
        diffs.append(d)
        if d == 0:
            hits[Level.SAME_BEAT] += 1
        if 0 <= e < len(bars) and 0 <= t < len(bars) and bars[e] == bars[t]:
            hits[Level.SAME_BAR] += 1
        if abs(d) <= BEATS_PER_BAR:
            hits[Level.WITHIN_1_BAR] += 1
    return RoleOutcome(truth=tru, estimated=est, hits=hits, diffs=tuple(diffs))


def compare_track(truth: TrackTruth, estimate: Estimate | None) -> TrackOutcome:
    bars = bar_numbers(truth.beats)
    cues = estimate.cues if estimate is not None else ()
    roles = {
        role: compare_role([c.beat_index for c in cues if c.role == role], truth_beats, bars)
        for role, truth_beats in truth.roles.items()
    }
    needs_review = estimate.needs_review if estimate is not None else True
    return TrackOutcome(truth.track_id, roles, estimate is not None, needs_review)


def score(tracks: Sequence[TrackOutcome]) -> Scores:
    roles: dict[Role, RoleScore] = {}
    for role in MVP_ROLES:
        outcomes = [t.roles[role] for t in tracks if role in t.roles]
        roles[role] = RoleScore(
            n_tracks=len(outcomes),
            n_estimated=sum(len(o.estimated) for o in outcomes),
            n_truth=sum(len(o.truth) for o in outcomes),
            hits={lv: sum(o.hits[lv] for o in outcomes) for lv in Level},
            none_tracks=sum(1 for o in outcomes if not o.truth),
            none_correct=sum(1 for o in outcomes if not o.truth and not o.estimated),
        )
    known = [t for t in tracks if t.all_correct is not None]
    not_flagged = [t for t in known if not t.needs_review]
    return Scores(
        roles=roles,
        m2=Ratio(sum(1 for t in known if t.all_correct), len(known)),
        m3=Ratio(sum(1 for t in not_flagged if t.all_correct), len(not_flagged)),
        m4=Ratio(sum(1 for t in tracks if t.needs_review), len(tracks)),
        n_tracks=len(tracks),
        n_missing_estimate=sum(1 for t in tracks if not t.has_estimate),
    )


def evaluate(truths: Iterable[TrackTruth], estimates: Mapping[str, Estimate]) -> Evaluation:
    """正解のある曲ごとに推定と比べ、M1〜M4 を出す。推定がない曲は「何も出さなかった」と数える。

    推定のほうにだけある曲（正解のない曲）は数えない。
    """
    tracks = tuple(compare_track(t, estimates.get(t.track_id)) for t in truths)
    return Evaluation(tracks, score(tracks))
