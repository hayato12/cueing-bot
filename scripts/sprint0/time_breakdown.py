"""Sprint 0: 手作業のキュー打ちの時間を、作業の種類ごとに測るラップタイマー。

使い方（Mac のターミナル。標準ライブラリだけで動く）:

    python3 scripts/sprint0/time_breakdown.py
    python3 scripts/sprint0/time_breakdown.py --out ~/llm/cueing-bot/data/sprint0

作業の種類が変わるたびに 1 キー押す。押した時点から次に押すまでの時間が、その種類に数えられる。

    i  イントロのキュー（A メロの頭・その 2L 前など）
    m  メイン（ホットキュー）
    n  抜け
    o  アウトロ（ホットキュー H）
    g  グリッドの修正
    x  それ以外（聴いているだけ、曲を選ぶ、迷っている、など）
    Enter  次の曲へ（今の曲を閉じ、次の曲を「それ以外」で始める）
    u  直前のキーを取り消す（押し間違い用）
    q  終わる（今の曲も閉じる）

結果は CSV（区間ごとの明細）に保存し、終わったときに曲ごと・種類ごとの合計を表示する。
曲名は記録しないので、CSV に個人データは入らない。それでもリポジトリの外（data フォルダ）に置く。
"""

from __future__ import annotations

import argparse
import csv
import sys
import termios
import time
import tty
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

CATEGORIES = {
    "i": "intro",
    "m": "main",
    "n": "break",
    "o": "outro",
    "g": "grid",
    "x": "other",
}
LABELS_JA = {
    "intro": "イントロ",
    "main": "メイン",
    "break": "抜け",
    "outro": "アウトロ",
    "grid": "グリッド",
    "other": "それ以外",
}
DEFAULT_OUT = Path.home() / "llm" / "cueing-bot" / "data" / "sprint0"


@dataclass
class Segment:
    track: int
    category: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return self.end - self.start


def read_key() -> str:
    """Enter を待たずに 1 文字読む（ターミナルを一時的に raw モードにする）。"""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def fmt(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def summarize(segments: list[Segment]) -> str:
    tracks = sorted({s.track for s in segments})
    cats = list(LABELS_JA)
    header = ["曲"] + [LABELS_JA[c] for c in cats] + ["合計"]
    rows = [header]
    totals = dict.fromkeys(cats, 0.0)
    for t in tracks:
        per = dict.fromkeys(cats, 0.0)
        for s in segments:
            if s.track == t:
                per[s.category] += s.seconds
        for c in cats:
            totals[c] += per[c]
        rows.append([str(t)] + [fmt(per[c]) for c in cats] + [fmt(sum(per.values()))])
    grand = sum(totals.values())
    rows.append(["計"] + [fmt(totals[c]) for c in cats] + [fmt(grand)])
    if grand > 0:
        rows.append(["割合"] + [f"{totals[c] / grand:.0%}" for c in cats] + ["100%"])
    return "\n".join("\t".join(r) for r in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="CSV の保存先フォルダ")
    args = parser.parse_args()

    out_dir: Path = args.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"time-breakdown-{datetime.now():%Y%m%d-%H%M%S}.csv"

    print(__doc__.split("作業の種類が変わるたびに")[1].split("結果は")[0])
    print("最初の作業のキーを押すと、1 曲目の計測が始まります。最後の曲が終わったら q を押してください。\n")

    segments: list[Segment] = []
    track = 1
    current: tuple[str, float] | None = None  # (種類, 始めた時刻)

    def close_current(now: float) -> None:
        nonlocal current
        if current is not None:
            segments.append(Segment(track, current[0], current[1], now))
            current = None

    while True:
        key = read_key()
        now = time.monotonic()
        if key in CATEGORIES:
            close_current(now)
            current = (CATEGORIES[key], now)
            print(f"[曲 {track}] {LABELS_JA[current[0]]}")
        elif key in ("\n", "\r"):
            close_current(now)
            took = sum(s.seconds for s in segments if s.track == track)
            track += 1
            current = ("other", now)  # 次の曲を読み込むなどの時間は「それ以外」に数える
            print(f"--- 前の曲は {fmt(took)}。曲 {track} を始めました（今は「それ以外」）---")
        elif key == "u":
            if current is not None:
                print(f"[曲 {track}] 取り消し：{LABELS_JA[current[0]]}（前の区間に戻します）")
                current = None
                if segments and segments[-1].track == track:
                    last = segments.pop()
                    current = (last.category, last.start)
                    print(f"[曲 {track}] {LABELS_JA[current[0]]} を続けます")
        elif key == "q":
            close_current(now)
            break

    t0 = segments[0].start if segments else 0.0
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["track", "category", "start_s", "end_s", "seconds"])
        for s in segments:
            w.writerow([s.track, s.category, f"{s.start - t0:.1f}", f"{s.end - t0:.1f}", f"{s.seconds:.1f}"])

    print("\n" + summarize(segments))
    print(f"\n保存しました：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
