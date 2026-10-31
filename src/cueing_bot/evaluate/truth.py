"""正解の形と、手動キューから正解を取り出す処理（評価データ a）。

正解は「オーナーが実際に打つ位置」（requirements.md 1 章）。手動キューの役割（どれが A メロの頭か）は
DB に書かれていないので、cueing-theory.md のルールから推し量る。スパイク 1 では、この推し量り方が
オーナーの答えと 10 曲中 7 曲で合った。外れる分は評価データ b（オーナーが確かめたもの）で補う。
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from cueing_bot.evaluate.beats import nearest_beat, two_l_beats
from cueing_bot.model import HOT_CUE_TYPES, Beat, CueType, ExistingCues, Role

TRUTH_VERSION = "a-v1"
"""正解の取り出し方の版。ルールを変えたら上げる。版が違う評価の結果は、前回と比べられない。"""

DEFAULT_SNAP_TOLERANCE_MS = 30.0
"""手動キューを一番近い拍に寄せるときに許すずれ。これより大きいキューがある曲は外す。

仮の値。Mac で手動キューのずれの分布を見てから決める（requirements.md 1 章「幅は Sprint 1 で決める」）。
"""


_KNOWN_KINDS = frozenset(int(c) for c in CueType)


@dataclass(frozen=True)
class TrackTruth:
    """1 曲ぶんの正解。

    `roles` の値は、その役割の正解の拍の番号（昇順）。空のタプルは「その役割の正解はない」（イントロが
    2L より短い、アウトロを使わない曲、など）。`roles` に入っていない役割は「分からない」なので評価しない。
    """

    track_id: str
    beats: tuple[Beat, ...]
    """正解を取り出したときのグリッド。「同じ小節」の判定に使う。"""
    roles: Mapping[Role, tuple[int, ...]]


class ExcludeReason(StrEnum):
    """曲を評価データから外した理由。"""

    NO_GRID = "no_grid"
    """グリッドが短すぎて BPM を出せない。"""
    OFF_GRID = "off_grid"
    """拍から大きくずれた手動キューがある（グリッドを直したあとに打ったキューなど）。"""
    TOO_FEW_MEMORY_CUES = "too_few_memory_cues"
    """メモリーキューが 2 つ未満で、イントロのかたまりを見つけられない。"""
    WRITTEN_BY_APP = "written_by_app"
    """アプリが書いた曲（書き込みの記録にある）。正解の元が手動キューでなくなっている。"""


class RoleExcludeReason(StrEnum):
    """曲は使うが、1 つの役割だけを外した理由。"""

    MINUS_2L_NOT_CUED = "minus_2l_not_cued"
    """イントロが 2L 以上あるのに、A メロの頭の 2L 前にメモリーキューがない。"""


@dataclass(frozen=True)
class Extracted:
    truth: TrackTruth
    role_excluded: Mapping[Role, RoleExcludeReason]


@dataclass(frozen=True)
class Excluded:
    track_id: str
    reason: ExcludeReason
    detail: str = ""


def extract_truth(
    cues: ExistingCues,
    beats: Sequence[Beat],
    *,
    snap_tolerance_ms: float = DEFAULT_SNAP_TOLERANCE_MS,
) -> Extracted | Excluded:
    """手動キューから 4 つの役割の正解を取り出す（評価データ a）。

    - A メロの頭：最初のメモリーキューから、間が 2L 以内で続くメモリーキューをイントロのかたまりと見て、
      その最後のキュー（スパイク 1 と同じ）
    - その 2L 前：A メロの頭のちょうど 2L 前にメモリーキューがあれば、それ。イントロのかたまりが 2L より
      短ければ「ない」。2L 以上あるのに打っていなければ、この役割だけ外す
    - メインのホット：ホット A〜G の位置を全部
    - アウトロの H：ホット H の位置。なければ「ない」

    ループと、知らない種類（`CueType` にない `Kind`）のキューは使わない。
    """
    beats = tuple(beats)
    track_id = cues.track_id
    if len(beats) < 2:
        return Excluded(track_id, ExcludeReason.NO_GRID)

    memory: set[int] = set()
    hot_main: set[int] = set()
    hot_h: set[int] = set()
    for cue in cues.cues:
        if cue.is_loop or cue.cue_type not in _KNOWN_KINDS:
            continue
        index, offset = nearest_beat(beats, cue.time_ms)
        if abs(offset) > snap_tolerance_ms:
            return Excluded(
                track_id,
                ExcludeReason.OFF_GRID,
                f"拍から {offset:+.0f} ms ずれたキューがある",
            )
        kind = CueType(cue.cue_type)
        if kind == CueType.MEMORY:
            memory.add(index)
        elif kind == CueType.HOT_H:
            hot_h.add(index)
        elif kind in HOT_CUE_TYPES:
            hot_main.add(index)

    if len(memory) < 2:
        return Excluded(track_id, ExcludeReason.TOO_FEW_MEMORY_CUES)

    two_l = two_l_beats(beats)
    ordered = sorted(memory)
    block = [ordered[0]]
    for index in ordered[1:]:
        if index - block[-1] > two_l:
            break
        block.append(index)
    intro_end = block[-1]

    roles: dict[Role, tuple[int, ...]] = {
        Role.INTRO_END: (intro_end,),
        Role.MAIN_HOT: tuple(sorted(hot_main)),
        Role.OUTRO_HOT: tuple(sorted(hot_h)),
    }
    role_excluded: dict[Role, RoleExcludeReason] = {}
    minus_2l = intro_end - two_l
    if minus_2l in memory:
        roles[Role.INTRO_END_MINUS_2L] = (minus_2l,)
    elif intro_end - block[0] < two_l:
        roles[Role.INTRO_END_MINUS_2L] = ()
    else:
        role_excluded[Role.INTRO_END_MINUS_2L] = RoleExcludeReason.MINUS_2L_NOT_CUED

    return Extracted(TrackTruth(track_id, beats, roles), role_excluded)


@dataclass(frozen=True)
class DatasetA:
    """評価データ a（手動キューから自動で作ったもの）。"""

    truths: tuple[TrackTruth, ...]
    excluded: tuple[Excluded, ...]
    role_excluded: Mapping[str, Mapping[Role, RoleExcludeReason]]
    """曲の ID ごとの、外した役割と理由。"""

    def excluded_counts(self) -> dict[str, int]:
        """外した理由ごとの数。曲ごと外したものと、役割だけ外したものを両方数える。"""
        counts: dict[str, int] = {}
        for e in self.excluded:
            counts[e.reason.value] = counts.get(e.reason.value, 0) + 1
        for reasons in self.role_excluded.values():
            for role, reason in reasons.items():
                key = f"{role.value}:{reason.value}"
                counts[key] = counts.get(key, 0) + 1
        return counts


def build_dataset_a(
    tracks: Iterable[tuple[ExistingCues, Sequence[Beat]]],
    written_by_app: Collection[str] = frozenset(),
    *,
    snap_tolerance_ms: float = DEFAULT_SNAP_TOLERANCE_MS,
) -> DatasetA:
    """手動キューのある曲から評価データ a を作る。アプリが書いた曲は外す（S1）。"""
    truths: list[TrackTruth] = []
    excluded: list[Excluded] = []
    role_excluded: dict[str, Mapping[Role, RoleExcludeReason]] = {}
    for cues, beats in tracks:
        if cues.track_id in written_by_app:
            excluded.append(Excluded(cues.track_id, ExcludeReason.WRITTEN_BY_APP))
            continue
        result = extract_truth(cues, beats, snap_tolerance_ms=snap_tolerance_ms)
        if isinstance(result, Excluded):
            excluded.append(result)
            continue
        truths.append(result.truth)
        if result.role_excluded:
            role_excluded[cues.track_id] = result.role_excluded
    return DatasetA(tuple(truths), tuple(excluded), role_excluded)
