"""解析ファイルの中身（PQTZ・PSSI）を `model` の形に直す。pyrekordbox には依存しない純粋な関数だけを置く。"""

from __future__ import annotations

import hashlib
import itertools
from collections.abc import Iterable, Sequence

from cueing_bot.model import Beat, Phrase

# フレーズの種類（PSSI の kind）。番号の意味は曲の mood（1=high、2=mid、3=low）で変わる。
# 出典：Deep Symmetry「Rekordbox Export Structure Analysis」の Song Structure の節（スパイク 2）
PHRASE_LABELS: dict[int, dict[int, str]] = {
    1: {1: "Intro", 2: "Up", 3: "Down", 5: "Chorus", 6: "Outro"},
    2: {
        1: "Intro",
        2: "Verse1",
        3: "Verse2",
        4: "Verse3",
        5: "Verse4",
        6: "Verse5",
        7: "Verse6",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
    3: {
        1: "Intro",
        2: "Verse1",
        3: "Verse1",
        4: "Verse1",
        5: "Verse2",
        6: "Verse2",
        7: "Verse2",
        8: "Bridge",
        9: "Chorus",
        10: "Outro",
    },
}


def beats_from_pqtz(beat_in_bar: Sequence[int], times_s: Sequence[float]) -> tuple[Beat, ...]:
    """PQTZ の「小節内の拍番号」と「時刻（秒）」の列から `Beat` の列を作る。"""
    if len(beat_in_bar) != len(times_s):
        raise ValueError("PQTZ の拍番号と時刻の数が合いません")
    beats = tuple(
        Beat(time_ms=float(t) * 1000.0, beat_in_bar=int(b))
        for b, t in zip(beat_in_bar, times_s, strict=True)
    )
    for prev, cur in itertools.pairwise(beats):
        if cur.time_ms <= prev.time_ms:
            raise ValueError("PQTZ の時刻が増えていません")
    return beats


def phrases_from_pssi(
    mood: int, entries: Iterable[tuple[int, int]], n_beats: int
) -> tuple[Phrase, ...]:
    """PSSI の mood と (頭の拍, 種類) の列から `Phrase` の列を作る。

    PSSI の拍は 1 始まりの通し番号なので、0 始まりの添字に直す。グリッドの外を指すフレーズは捨てる。
    """
    labels = PHRASE_LABELS.get(mood, {})
    out: list[Phrase] = []
    for beat_no, kind in entries:
        index = int(beat_no) - 1
        if 0 <= index < n_beats:
            out.append(Phrase(index, int(kind), labels.get(int(kind), f"kind{int(kind)}")))
    return tuple(sorted(out, key=lambda p: p.beat_index))


def fingerprint(path: str, size: int, mtime_ns: int, beats: Sequence[Beat]) -> str:
    """音源（パス・大きさ・更新日時）とグリッドから、変わったかを見分ける値を作る（N9）。"""
    h = hashlib.sha256()
    h.update(f"{path}\0{size}\0{mtime_ns}\0".encode())
    for b in beats:
        h.update(f"{b.time_ms:.3f}:{b.beat_in_bar};".encode())
    return h.hexdigest()[:16]
