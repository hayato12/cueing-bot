"""スパイク 2：Rekordbox のフレーズ解析を読み出し、オーナーの手動キューと比べる。

使い方（リポジトリ直下で。pyrekordbox を入れた使い捨ての venv を使う）:
    .venv/bin/python scripts/spikes/spike2_phrase_vs_cues.py <エクスポートした XML> <曲ごとの結果を書く CSV>

読むもの（どれも読み取りのみ。master.db は開かない）:
    - エクスポートした XML：手動キューの位置（秒）と曲の情報、プレイリスト
    - 解析ファイル ANLZ0000.DAT：曲のファイルパス（PPTH）とビートグリッド（PQTZ）
    - 解析ファイル ANLZ0000.EXT：フレーズ解析（PSSI）

曲と解析ファイルの対応は、DAT に入っているファイル名で取る（DB を使わずに済む）。
CSV には曲名が入るので、リポジトリの外（data/ など）に書くこと。
"""

import csv
import glob
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np  # pyrekordbox と一緒に入る数値計算ライブラリ。ビートの時刻は numpy の配列で返ってくる
from pyrekordbox.anlz import AnlzFile

ANLZ_ROOT = Path.home() / "Library/Pioneer/rekordbox/share/PIONEER/USBANLZ"

# フレーズの種類（PSSI の kind）。番号の意味は曲の mood（1=high, 2=mid, 3=low）で変わる。
# 出典：Deep Symmetry「Rekordbox Export Structure Analysis」の Song Structure の節
PHRASE_NAMES = {
    1: {1: "Intro", 2: "Up", 3: "Down", 5: "Chorus", 6: "Outro"},
    2: {1: "Intro", 2: "Verse1", 3: "Verse2", 4: "Verse3", 5: "Verse4", 6: "Verse5", 7: "Verse6",
        8: "Bridge", 9: "Chorus", 10: "Outro"},
    3: {1: "Intro", 2: "Verse1", 3: "Verse1", 4: "Verse1", 5: "Verse2", 6: "Verse2", 7: "Verse2",
        8: "Bridge", 9: "Chorus", 10: "Outro"},
}


# @dataclass は、フィールドを並べるだけでコンストラクタなどを作ってくれる仕組み（TS の interface＋class に近い）
@dataclass
class Phrase:
    beat: int  # グリッド上の通し番号（1 始まり）。フレーズの頭の拍
    name: str


@dataclass
class Track:
    path: str
    name: str
    bpm: float
    cues: list[tuple[int, float]]  # (Num, 秒)。Num=-1 がメモリー、0〜7 がホット A〜H
    folders: set[str] = field(default_factory=set)  # その曲が入っているプレイリストの一番上のフォルダ名


def load_export(path: str) -> dict[str, Track]:
    """エクスポート XML から、手動キューのある曲を {ファイルパス: Track} で返す。"""
    root = ET.parse(path).getroot()
    tracks: dict[str, Track] = {}
    by_id: dict[str, Track] = {}
    for t in root.find("COLLECTION"):
        cues = [(int(m.get("Num")), float(m.get("Start"))) for m in t.findall("POSITION_MARK")
                if m.get("Type") == "0"]  # ループ（Type=4）は除く
        if not cues:
            continue
        # Location は "file://localhost/Users/..." 形式で、日本語などは %E3%81... に変換されている
        p = urllib.parse.unquote(t.get("Location").removeprefix("file://localhost"))
        tr = Track(p, t.get("Name") or "", float(t.get("AverageBpm") or 0), cues)
        tracks[p] = tr
        by_id[t.get("TrackID")] = tr

    # プレイリストの一番上のフォルダ（HOUSE など）を曲に付ける。ジャンル別に集計するため
    top = root.find("PLAYLISTS/NODE")
    for folder in top.findall("NODE"):
        for pl_track in folder.iter("TRACK"):
            tr = by_id.get(pl_track.get("Key"))
            if tr:
                tr.folders.add(folder.get("Name"))
    return tracks


def scan_anlz(wanted: set[str]) -> dict[str, Path]:
    """解析フォルダの ANLZ0000.DAT を全部見て、{曲のファイルパス: DAT のパス} を返す。

    Rekordbox 7 の DAT には、パスが "?/ファイル名" の形でしか入っていなかった（フォルダが分からない）。
    そのため、ファイル名で対応を取る。同じファイル名の曲・解析ファイルが複数あるものは、
    取り違えを避けるために使わない
    """
    by_name: dict[str, list[str]] = {}
    for p in wanted:
        by_name.setdefault(Path(p).name, []).append(p)  # setdefault は「なければ空リストを入れてから返す」
    dats_by_name: dict[str, list[Path]] = {}
    for dat in glob.glob(str(ANLZ_ROOT / "*/*/ANLZ0000.DAT")):
        try:
            p = AnlzFile.parse_file(dat).get("path")
        except Exception:  # 壊れた・形式の違うファイルは飛ばす
            continue
        dats_by_name.setdefault(Path(p).name, []).append(Path(dat))
    found = {}
    for name, paths in by_name.items():
        dats = dats_by_name.get(name, [])
        if len(paths) == 1 and len(dats) == 1:
            found[paths[0]] = dats[0]
    return found


def read_analysis(dat: Path) -> tuple[np.ndarray, np.ndarray, int, list[Phrase]] | None:
    """ビートグリッド（各拍の時刻と小節内の拍番号）、mood、フレーズの列を返す。フレーズ解析がなければ None。"""
    ext = dat.with_suffix(".EXT")
    if not ext.exists():
        return None
    e = AnlzFile.parse_file(ext)
    if "PSSI" not in e.tag_types:
        return None
    pssi = e.get_tag("PSSI").content
    beats_in_bar, _bpms, times = AnlzFile.parse_file(dat).get_tag("PQTZ").get()
    names = PHRASE_NAMES.get(pssi.mood, {})
    phrases = [Phrase(en.beat, names.get(en.kind, f"kind{en.kind}")) for en in pssi.entries]
    return times, beats_in_bar, pssi.mood, phrases


def nearest_beat(times: np.ndarray, sec: float) -> int:
    """秒に一番近い拍の通し番号（1 始まり）を返す。"""
    return int(np.abs(times - sec).argmin()) + 1


def blocks(phrases: list[Phrase], end_beat: int) -> list[tuple[str, int, int]]:
    """同じ名前のフレーズが続いたら 1 つにまとめ、(名前, 頭の拍, 終わりの次の拍) の列にする。"""
    out: list[tuple[str, int, int]] = []
    for i, ph in enumerate(phrases):
        nxt = phrases[i + 1].beat if i + 1 < len(phrases) else end_beat
        if out and out[-1][0] == ph.name:
            out[-1] = (ph.name, out[-1][1], nxt)
        else:
            out.append((ph.name, ph.beat, nxt))
    return out


def classify(diff_beats: int | None) -> str:
    """ずれ（拍）を「一致／1 小節以内／それ以上」に分ける。"""
    if diff_beats is None:
        return "対応なし"
    d = abs(diff_beats)
    return "一致" if d == 0 else "1小節以内" if d <= 4 else "ずれ大"


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    tracks = load_export(sys.argv[1])
    dats = scan_anlz(set(tracks))

    rows = []
    stats = {k: Counter() for k in ("all_cues", "intro_end", "outro_H", "main_hot")}
    house = {k: Counter() for k in stats}
    moods = Counter()
    no_phrase = 0
    parse_errors: Counter = Counter()
    for p, tr in tracks.items():
        if p not in dats:
            continue
        try:
            res = read_analysis(dats[p])
        except Exception as err:  # pyrekordbox が読めない形式の解析ファイルがあった。数えて飛ばす
            parse_errors[type(err).__name__] += 1
            continue
        if res is None:
            no_phrase += 1
            continue
        times, _bib, mood, phrases = res
        moods[mood] += 1
        bl = blocks(phrases, len(times) + 1)
        bounds = sorted({b[1] for b in bl} | {bl[-1][2]})  # フレーズの区切り（拍）
        two_l = (8 if tr.bpm > 120 else 4) * 2 * 4  # 2L を拍で。L は BPM 120 以下で 4 小節、超えると 8 小節
        is_house = "HOUSE" in tr.folders
        cue_beats = [(num, nearest_beat(times, sec)) for num, sec in tr.cues]

        def record(kind: str, diff: int | None, detail: str) -> None:
            c = classify(diff)
            stats[kind][c] += 1
            if is_house:
                house[kind][c] += 1
            rows.append([tr.name, tr.bpm, mood, kind, detail, diff if diff is not None else "", c])

        # 1. 手動キューが、フレーズの区切りにどれだけ乗っているか
        for num, b in cue_beats:
            d = min((b - x for x in bounds), key=abs)
            record("all_cues", d, f"Num={num}")

        # 2. A メロの頭（＝イントロの終わり）：イントロの次のフレーズの頭に、手動キューがあるか
        if bl[0][0] == "Intro" and len(bl) > 1:
            target = bl[0][2]
            d = min((b - target for _, b in cue_beats), key=abs)
            record("intro_end", d, f"intro_end_beat={target}")

        # 3. ホットキュー H と、Outro の頭
        h = [b for num, b in cue_beats if num == 7]
        outro = [x for x in bl if x[0] == "Outro"]
        if h:
            record("outro_H", (h[0] - outro[-1][1]) if outro else None, "")

        # 4. ホットキュー A〜G と「2 回目以降の Chorus の終わりの 2L 前」（cueing-theory.md 3.2）
        hots = sorted(b for num, b in cue_beats if 0 <= num <= 6)
        targets = [end - two_l for name, _s, end in bl if name == "Chorus"][1:]
        for b in hots:
            record("main_hot", min((b - t for t in targets), key=abs) if targets else None, "")

    with open(sys.argv[2], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "bpm", "mood", "check", "detail", "diff_beats", "result"])
        w.writerows(rows)

    print(f"手動キューのある曲: {len(tracks)} / 解析ファイルあり: {len(dats)} / フレーズ解析なし: {no_phrase} / 読めなかった: {dict(parse_errors)}")
    print(f"mood の内訳（1=high, 2=mid, 3=low）: {dict(moods)}")
    labels = {"all_cues": "手動キューがフレーズの区切りに乗っているか",
              "intro_end": "イントロの終わりに手動キューがあるか",
              "outro_H": "ホット H と Outro の頭",
              "main_hot": "ホット A〜G と 2 回目以降の Chorus の終わりの 2L 前"}
    for key, label in labels.items():
        for scope, st in (("全体", stats[key]), ("HOUSE フォルダ", house[key])):
            n = sum(st.values())
            parts = ", ".join(f"{c} {st[c]}（{st[c] / n:.0%}）" for c in ("一致", "1小節以内", "ずれ大", "対応なし") if st[c])
            print(f"{label}［{scope}］ n={n}: {parts}")


if __name__ == "__main__":
    main()
