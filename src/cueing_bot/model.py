"""モジュール間で受け渡すデータの形（architecture.md 3 章）。

外部のライブラリ（pyrekordbox・Demucs など）に依存しない。`estimate` と `evaluate` はこのモジュールだけを見る。
`@dataclass(frozen=True)` は、TypeScript の `readonly` な型に近い（作ったあとに書き換えられない）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


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


HOT_CUE_TYPES = frozenset(
    {
        CueType.HOT_A,
        CueType.HOT_B,
        CueType.HOT_C,
        CueType.HOT_D,
        CueType.HOT_E,
        CueType.HOT_F,
        CueType.HOT_G,
    }
)
"""2 回目以降のメインに使うホットキュー（A〜G）。H はアウトロ専用（cueing-theory.md 3.2・3.3）。"""


class Role(StrEnum):
    """推定キューの役割。評価と表示のためのラベル（architecture.md 3 章）。

    `StrEnum` は値が文字列の列挙型で、JSON にそのまま書ける。抜けのキューなどを足すときは、ここに増やす。
    """

    INTRO_END = "intro_end"
    """A メロの頭（＝イントロの終わり）。メモリーキュー。"""
    INTRO_END_MINUS_2L = "intro_end_minus_2l"
    """A メロの頭の 2L 小節前。メモリーキュー。"""
    MAIN_HOT = "main_hot"
    """2 回目以降のメインの終わりの 2L 前。ホットキュー A〜G。"""
    OUTRO_HOT = "outro_hot"
    """アウトロの頭。ホットキュー H。"""


MVP_ROLES: tuple[Role, ...] = (
    Role.INTRO_END,
    Role.INTRO_END_MINUS_2L,
    Role.MAIN_HOT,
    Role.OUTRO_HOT,
)
"""MVP で必ず打つ 4 つのキューの役割。"""


@dataclass(frozen=True)
class ReviewReason:
    """「要確認」の理由。`code` で絞り込み、`message` を一覧に出す（S4・S5）。"""

    code: str
    message: str


@dataclass(frozen=True)
class EstimatedCue:
    """推定キュー 1 つ。位置はグリッドの拍の番号で持つ（architecture.md 3 章「位置の表し方」）。"""

    cue_type: CueType
    beat_index: int
    """`TrackInput.beats` の添字（0 始まり）。ms に直すのは書くときだけ。"""
    role: Role
    review: tuple[ReviewReason, ...] = ()
    """このキューの要確認の理由。なければ空。"""


@dataclass(frozen=True)
class Estimate:
    """1 曲ぶんの推定結果。`estimate` が作り、`store`・`report`・`evaluate`・`writer` が使う。"""

    track_id: str
    fingerprint: str
    """推定に使った `TrackInput.fingerprint`。書く直前に今の値と比べる。"""
    cues: tuple[EstimatedCue, ...]
    track_review: tuple[ReviewReason, ...]
    """曲全体の要確認の理由。なければ空。"""
    estimator: str
    """推定の名前と版（例：`rules-v1`）。評価の記録に残す。"""

    @property
    def needs_review(self) -> bool:
        """曲かキューのどれかに要確認の理由があるか（M3・M4）。"""
        return bool(self.track_review) or any(c.review for c in self.cues)
