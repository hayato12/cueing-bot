"""スパイク 3：取り込み前後のエクスポート XML を並べ、テスト用 4 曲のキューと曲の情報を比べる。

使い方:
    python3 scripts/spikes/spike3_compare.py <取り込み前.xml> <取り込み後.xml> [<2 回目の後.xml> ...]

読み取りのみ。標準ライブラリだけで動く。
"""

import sys
import xml.etree.ElementTree as ET

KIND = {-1: "メモリー"} | {i: f"ホット {'ABCDEFGH'[i]}" for i in range(8)}  # | は辞書の結合
# 曲の情報が消えていないかを見る属性
WATCH = ("Name", "Artist", "AverageBpm", "TotalTime", "Genre", "Tonality")


def spike_tracks(path: str) -> dict[str, ET.Element]:
    """XML からファイル名に spike3-X- を含む曲を {"A": TRACK, ...} で返す。"""
    found = {}
    for tr in ET.parse(path).getroot().iter("TRACK"):
        loc = tr.get("Location") or ""
        for key in "ABCD":
            if f"spike3-{key}-" in loc and tr.get("TrackID"):
                found[key] = tr
    return found


def describe(tr: ET.Element | None) -> list[str]:
    """1 曲ぶんの情報を、比べやすいように文字列のリストにする。"""
    if tr is None:
        return ["（曲が見つからない）"]
    lines = [f"{k}={tr.get(k)}" for k in WATCH]
    tempos = tr.findall("TEMPO")
    lines.append(f"TEMPO {len(tempos)} 個" + (f"（先頭 Inizio={tempos[0].get('Inizio')} Bpm={tempos[0].get('Bpm')}）" if tempos else ""))
    marks = sorted(tr.findall("POSITION_MARK"), key=lambda m: (int(m.get("Num")), float(m.get("Start"))))
    for m in marks:
        color = f" 色={m.get('Red')},{m.get('Green')},{m.get('Blue')}" if m.get("Red") else ""
        lines.append(f"{KIND.get(int(m.get('Num')), m.get('Num'))} @{float(m.get('Start')):.3f}s 名前='{m.get('Name')}' Type={m.get('Type')}{color}")
    return lines


def main() -> None:
    paths = sys.argv[1:]
    if len(paths) < 2:
        raise SystemExit(__doc__)
    snapshots = [spike_tracks(p) for p in paths]
    for key in "ABCD":
        print(f"=== 曲 {key} ===")
        for path, snap in zip(paths, snapshots):
            print(f"--- {path}")
            for line in describe(snap.get(key)):
                print("   ", line)
        print()


if __name__ == "__main__":
    main()
