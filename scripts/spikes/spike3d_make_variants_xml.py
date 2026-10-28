"""スパイク 3 の 4 回目：メモリーキューが 1 つしか入らない原因を切り分けるための XML を作る。

使い方:
    python3 scripts/spikes/spike3d_make_variants_xml.py <最新のエクスポート XML> <出力する XML>
    例: python3 scripts/spikes/spike3d_make_variants_xml.py \\
            ~/llm/cueing-bot/data/spike3/round3/after.xml ~/llm/cueing-bot/data/spike3/round4/import.xml

仮説:
    Rekordbox の取り込みは、キューを POSITION_MARK の Num ごとに 1 つの枠として扱っている。
    メモリーキューはどれも Num="-1" なので同じ枠を取り合い、最後に書いたものだけが残る。

確かめること（曲ごとに 1 つずつ変える）:
    E（コレクションにある曲）：メモリーキューの Num を -1・-2・-3 と変える → 3 つ入れば Num で区別されている
    F（コレクションにある曲）：メモリーキューに Num を書かない → 何が入るか
    G（コレクションにある曲）：ホット A・メモリー・メモリーループ・メモリーの順に書く → ループは別枠か
    N1（コレクションにない曲）：Num="-1" のメモリーキューを 3 つ。「コレクションにインポート」で取り込む
    N2（コレクションにない曲）：N1 と同じ中身。「プレイリストをインポート」で取り込む
        → 新しい曲として入るときだけ全部入るなら、既存の曲を更新する処理の問題

E・F・G は、エクスポートの <TRACK> の文字列をそのまま使い、POSITION_MARK の行だけを差し替える
（属性の順番や書式は Rekordbox の出力のまま）。N1・N2 は E を元に、TrackID・Location・追加日だけ変える。
N1・N2 の音源は E のコピーで、E と同じフォルダに置く（なければこのスクリプトがコピーする）。
"""

import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

# テスト用の曲はデモ曲なので BPM が一定。最初の拍の位置と 1 小節の長さから秒を出す
DEMO1_FIRST_BEAT, DEMO1_BAR = 0.023, 4 * 60 / 128  # Demo Track 1（128 BPM）
DEMO2_FIRST_BEAT, DEMO2_BAR = 0.024, 4 * 60 / 120  # Demo Track 2（120 BPM）


def at(first_beat: float, bar_len: float, bar: int) -> str:
    """小節番号（1 始まり）を、エクスポートと同じ小数 3 桁の秒にする。"""
    return f"{first_beat + (bar - 1) * bar_len:.3f}"


def mark(start: str, num: str | None, name: str, extra: str = "", type_: str = "0") -> str:
    """POSITION_MARK の行を 1 つ作る。num=None なら Num 属性を書かない。"""
    num_attr = "" if num is None else f' Num="{num}"'
    return f'      <POSITION_MARK Name="{name}" Type="{type_}" Start="{start}"{extra}{num_attr}/>'


def find_block(text: str, name_part: str) -> str:
    blocks = [m.group(0) for m in re.finditer(r"<TRACK TrackID=.*?</TRACK>", text, re.S)]
    hits = [b for b in blocks if name_part in b]
    if len(hits) != 1:
        raise SystemExit(f"'{name_part}' を含む曲が {len(hits)} 曲見つかりました（1 曲のはず）")
    return hits[0]


def replace_marks(block: str, marks: list[str]) -> str:
    """<TRACK> の中の POSITION_MARK（複数行にまたがるものも）を消して、marks を TEMPO の後ろに入れる。"""
    without = re.sub(r"\s*<POSITION_MARK.*?/>", "", block, flags=re.S)
    head, tail = without.rsplit("\n", 1)  # tail は "    </TRACK>"
    return head + "\n" + "\n".join(marks) + "\n" + tail.lstrip("\n")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    export_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    text = export_path.read_text(encoding="utf-8")
    d1 = lambda bar: at(DEMO1_FIRST_BEAT, DEMO1_BAR, bar)  # noqa: E731（lambda は TS のアロー関数）
    d2 = lambda bar: at(DEMO2_FIRST_BEAT, DEMO2_BAR, bar)  # noqa: E731
    tracks, log = [], []

    e = find_block(text, "spike3-E-")
    tracks.append(replace_marks(e, [mark(d1(b), n, f"r4-num{n}") for b, n in ((9, "-1"), (25, "-2"), (41, "-3"))]))
    log.append(f"E: メモリー {d1(9)}s(Num=-1)、{d1(25)}s(Num=-2)、{d1(41)}s(Num=-3)")

    f = find_block(text, "spike3-F-")
    tracks.append(replace_marks(f, [mark(d2(b), None, f"r4-nonum-bar{b}") for b in (9, 25, 41)]))
    log.append(f"F: メモリー {d2(9)}s、{d2(25)}s、{d2(41)}s（Num なし）")

    g = find_block(text, "spike3-G-")
    hot_a = re.search(r"<POSITION_MARK[^>]*?Num=\"0\".*?/>", g, re.S)
    if hot_a is None:
        raise SystemExit("G にホット A が見つかりません")
    tracks.append(
        replace_marks(
            g,
            [
                "      " + hot_a.group(0),  # 既存のホット A は書き戻す
                mark(d1(17), "-1", "r4-mem-bar17"),
                mark(d1(25), "-1", "r4-loop-bar25", extra=f' End="{d1(29)}"', type_="4"),
                mark(d1(41), "-1", "r4-mem-bar41"),
            ],
        )
    )
    log.append(f"G: ホット A を書き戻し、メモリー {d1(17)}s、メモリーループ {d1(25)}〜{d1(29)}s、メモリー {d1(41)}s")

    # コレクションにない曲：E の音源をコピーして、E と同じフォルダに置く
    e_loc = re.search(r'Location="([^"]+)"', e).group(1)
    e_file = Path(unquote(e_loc.removeprefix("file://localhost")))
    playlists = []
    for i, key in enumerate(("N1", "N2"), start=1):
        loc = e_loc.replace("spike3-E-multi", f"spike3-{key}-new")
        dst = e_file.with_name(f"spike3-{key}-new.mp3")
        if e_file.exists() and not dst.exists():
            shutil.copyfile(e_file, dst)
        block = re.sub(r'TrackID="\d+"', f'TrackID="9000000{i}"', e, count=1)
        block = block.replace(e_loc, loc)
        block = re.sub(r'DateAdded="[^"]+"', 'DateAdded="2026-10-28"', block, count=1)
        block = replace_marks(block, [mark(d1(b), "-1", f"r4-{key.lower()}-bar{b}") for b in (9, 25, 41)])
        tracks.append(block)
        playlists.append((f"spike3d-{key}", f"9000000{i}"))
        log.append(f"{key}: 新しい曲 {dst.name}。メモリー {d1(9)}s、{d1(25)}s、{d1(41)}s（すべて Num=-1）")

    header = text[: text.index("<COLLECTION")]
    nodes = "".join(
        f'      <NODE Name="{name}" Type="1" KeyType="0" Entries="1">\n        <TRACK Key="{tid}"/>\n      </NODE>\n'
        for name, tid in playlists
    )
    out = (
        header
        + f'<COLLECTION Entries="{len(tracks)}">\n    '
        + "\n    ".join(tracks)
        + "\n  </COLLECTION>\n"
        + f'  <PLAYLISTS>\n    <NODE Type="0" Name="ROOT" Count="{len(playlists)}">\n'
        + nodes
        + "    </NODE>\n  </PLAYLISTS>\n</DJ_PLAYLISTS>\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(out, encoding="utf-8")
    print("\n".join(log))
    print(f"書き出しました: {out_path}")


if __name__ == "__main__":
    main()
