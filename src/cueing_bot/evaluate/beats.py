"""グリッドの拍まわりの計算（ms から拍へ寄せる、小節番号、L の長さ）。"""

from __future__ import annotations

import bisect
import itertools
import statistics
from collections.abc import Sequence

from cueing_bot.model import Beat

BEATS_PER_BAR = 4
"""Rekordbox のグリッド（PQTZ）は 4 拍子だけ。"""


def nearest_beat(beats: Sequence[Beat], time_ms: float) -> tuple[int, float]:
    """`time_ms` に一番近い拍の番号と、そこからのずれ（ms。キューが拍より後ろなら正）を返す。"""
    if not beats:
        raise ValueError("グリッドが空です")
    times = [b.time_ms for b in beats]
    i = bisect.bisect_left(times, time_ms)
    candidates = [j for j in (i - 1, i) if 0 <= j < len(beats)]
    best = min(candidates, key=lambda j: abs(times[j] - time_ms))
    return best, time_ms - times[best]


def bar_numbers(beats: Sequence[Beat]) -> tuple[int, ...]:
    """拍ごとの小節番号。最初の小節の 1 拍目を 1 小節目とし、それより前の拍は 0 小節目にする。

    Rekordbox の画面の数え方と同じかは Mac で確かめる（Sprint 1 の計画「小節番号の数え方」）。
    """
    out: list[int] = []
    bar = 0
    for b in beats:
        if b.beat_in_bar == 1:
            bar += 1
        out.append(bar)
    return tuple(out)


def bar_start_beat(beats: Sequence[Beat], bar: int) -> int | None:
    """小節番号（1 始まり）の 1 拍目の拍の番号。グリッドの外なら None。"""
    seen = 0
    for i, b in enumerate(beats):
        if b.beat_in_bar == 1:
            seen += 1
            if seen == bar:
                return i
    return None


def bpm(beats: Sequence[Beat]) -> float:
    """拍の間隔の中央値から BPM を出す。テンポが途中で変わる曲でも、一番長く続くテンポに近くなる。"""
    if len(beats) < 2:
        raise ValueError("BPM を出すには 2 拍以上要ります")
    gaps = [b.time_ms - a.time_ms for a, b in itertools.pairwise(beats)]
    return 60_000.0 / statistics.median(gaps)


def l_bars(tempo: float) -> int:
    """L（基本単位）の小節数。BPM 120 以下なら 4 小節、120 を超えたら 8 小節（cueing-theory.md 2 章）。

    120 前後の曲は聴いて決めるルールだが、自動では見分けず、決められないときの扱い（120 以下）に寄せる。
    """
    # 拍の間隔から出した BPM は 120.0001 のようにぶれるので、Rekordbox の表示と同じ小数 2 桁で比べる
    return 8 if round(tempo, 2) > 120.0 else 4


def two_l_beats(beats: Sequence[Beat]) -> int:
    """2L を拍の数で表したもの。"""
    return l_bars(bpm(beats)) * 2 * BEATS_PER_BAR
