"""モジュール間で受け渡すデータの形（architecture.md 3 章）。

外部のライブラリ（pyrekordbox・Demucs など）に依存しない。`estimate` と `evaluate` はこのモジュールだけを見る。
`@dataclass(frozen=True)` は、TypeScript の `readonly` な型に近い（作ったあとに書き換えられない）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


@dataclass(frozen=True)
class Beat:
    """グリッドの 1 拍。"""

    time_ms: float
    """曲の頭からの時刻（ms）。"""
    beat_in_bar: int
    """小節内の拍番号（1〜4）。1 が小節の頭。"""


@dataclass(frozen=True)
class Phrase:
    """Rekordbox のフレーズ解析（PSSI）の 1 区間の頭。"""

    beat_index: int
    """頭の拍の番号（`TrackInput.beats` の添字。0 始まり）。"""
    kind: int
    """PSSI の種類の番号。意味は曲の mood で変わる（`label` を参照）。"""
    label: str
    """種類の名前（Intro・Chorus など）。表示とルールの読みやすさのため。"""


@dataclass(frozen=True)
class TrackInput:
    """推定に渡す曲の情報。**既存のキューは入れない**（評価の正解が紛れ込まないように）。"""

    id: str
    """`djmdContent.ID`。書き込みまでこの ID で曲を指す。"""
    title: str
    artist: str
    path: str
    """音源のファイルのパス。"""
    file_type: int
    """`djmdContent.FileType`（1=MP3、4=M4A など）。N10 の判定に使う。"""
    beats: tuple[Beat, ...]
    phrases: tuple[Phrase, ...]
    mood: int | None
    """PSSI の mood（1=high、2=mid、3=low）。フレーズ解析がなければ None。"""
    fingerprint: str
    """音源（パス・大きさ・更新日時）とグリッドから作る値。変わったら保存済みの結果を使わない（N9）。"""


class CueType(IntEnum):
    """`djmdCue.Kind` の値。0 がメモリーキュー、それ以外がホットキューのパッド（スパイク 4）。"""

    MEMORY = 0
    HOT_A = 1
    HOT_B = 2
    HOT_C = 3
    HOT_D = 5
    HOT_E = 6
    HOT_F = 7
    HOT_G = 8
    HOT_H = 9


@dataclass(frozen=True)
class ExistingCue:
    """既存のキュー 1 つ。"""

    cue_type: int
    """`djmdCue.Kind`。`CueType` の値のはずだが、知らない値もそのまま持つ。"""
    time_ms: int
    """`djmdCue.InMsec`。"""
    is_loop: bool
    """ループ（`OutMsec` が入っている）かどうか。"""


@dataclass(frozen=True)
class ExistingCues:
    """曲ごとの既存のキュー。`evaluate`（正解）と `writer`（決定 11）だけが使い、`estimate` には渡さない。"""

    track_id: str
    cues: tuple[ExistingCue, ...]
