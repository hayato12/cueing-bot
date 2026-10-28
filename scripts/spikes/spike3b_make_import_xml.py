"""スパイク 3 の追加実験：1 回目で分からなかった点を確かめるための、テスト用 XML を作る。

使い方:
    python3 scripts/spikes/spike3b_make_import_xml.py <エクスポートした XML> <出力する XML>

確かめること:
    E（キューなし）  ：メモリーキューを 3 つ書く → 全部入るか、最後の 1 つだけか
    F（メモリー 9・25 小節目）：新しい位置（41）を先、既存と同じ位置（25）を後に書く
        → 残ったのが 25 なら「最後の 1 つだけ入る」、41 なら「同じ位置は入らない」、両方なら複数入る
    G（ホット A・プレイリスト・myTag・レーティングあり）：メモリーキューを 1 つ書く
        → TrackID が変わっても、プレイリスト・myTag・レーティングが残るか

1 回目のスクリプトと同じく、読み取りのみ・標準ライブラリだけで動く。
"""

import sys
import xml.etree.ElementTree as ET

# 1 回目のスクリプトの関数を使い回す。
# python3 で直接実行すると、スクリプトのあるフォルダが import の検索先に入るので、
# 同じフォルダの spike3_make_import_xml.py をモジュールとして読み込める
from spike3_make_import_xml import MEMORY, add_mark, bar_to_sec, existing_marks, make_track


def build(src: dict[str, ET.Element]) -> tuple[list[ET.Element], list[str]]:
    out, log = [], []

    s = src["E"]
    t = make_track(s, minimal=False)
    for bar in (9, 25, 41):
        add_mark(t, MEMORY, bar_to_sec(s, bar), f"xml-mem-bar{bar}")
    out.append(t)
    log.append("E: メモリーを 9・25・41 小節目に 3 つ（" + ", ".join(f"{bar_to_sec(s, b):.3f}s" for b in (9, 25, 41)) + "）")

    s = src["F"]
    mems = sorted((m for m in existing_marks(s) if m["num"] == MEMORY), key=lambda m: m["start"])
    if len(mems) < 2:
        raise SystemExit("F の曲にメモリーキューを 2 つ（9・25 小節目）打ってください")
    t = make_track(s, minimal=False)
    add_mark(t, MEMORY, bar_to_sec(s, 41), "xml-mem-new-first")  # 新しい位置を先に書く
    add_mark(t, MEMORY, mems[1]["start"], "xml-mem-same-last")  # 既存と同じ位置を後に書く
    out.append(t)
    log.append(
        f"F: 新しい位置 {bar_to_sec(s, 41):.3f}s を先、既存と同じ {mems[1]['start']:.3f}s を後に書く。"
        f"既存 {mems[0]['start']:.3f}s は書かない"
    )

    s = src["G"]
    t = make_track(s, minimal=False)  # Rating や Colour などの属性もそのまま写る
    # 既存のホットキューは書き戻す（キューを残したい曲の書き方を兼ねて試す）
    for m in s.findall("POSITION_MARK"):
        t.append(m)
    add_mark(t, MEMORY, bar_to_sec(s, 17), "xml-mem-bar17")
    out.append(t)
    log.append(f"G: 既存のキューを書き戻し、メモリー {bar_to_sec(s, 17):.3f}s を追加。Rating={s.get('Rating')}")
    return out, log


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    root = ET.parse(sys.argv[1]).getroot()
    src = {}
    for tr in root.iter("TRACK"):
        for key in "EFG":
            if f"spike3-{key}-" in (tr.get("Location") or "") and tr.get("TrackID"):
                src[key] = tr
    missing = [k for k in "EFG" if k not in src]
    if missing:
        raise SystemExit(f"エクスポートに見つからない曲: {missing}")

    tracks, log = build(src)
    doc = ET.Element("DJ_PLAYLISTS", {"Version": "1.0.0"})
    ET.SubElement(doc, "PRODUCT", {"Name": "cueing-bot-spike3b", "Version": "0.0.0", "Company": ""})
    coll = ET.SubElement(doc, "COLLECTION", {"Entries": str(len(tracks))})
    coll.extend(tracks)  # extend はリストの要素をまとめて子要素に足す
    # PLAYLISTS がない XML では、Rekordbox の「rekordbox xml」に曲が 1 つも出なかった（2026-10-28。入れたら出た）。
    # 中身が使われなくても、ROOT のノードとプレイリストを 1 つ入れておく
    playlists = ET.SubElement(doc, "PLAYLISTS")
    root_node = ET.SubElement(playlists, "NODE", {"Type": "0", "Name": "ROOT", "Count": "1"})
    pl = ET.SubElement(
        root_node, "NODE", {"Name": "spike3b", "Type": "1", "KeyType": "0", "Entries": str(len(tracks))}
    )
    for t in tracks:
        ET.SubElement(pl, "TRACK", {"Key": t.get("TrackID")})
    ET.indent(doc)
    ET.ElementTree(doc).write(sys.argv[2], encoding="UTF-8", xml_declaration=True)
    print("\n".join(log))
    print(f"書き出しました: {sys.argv[2]}")


if __name__ == "__main__":
    main()
