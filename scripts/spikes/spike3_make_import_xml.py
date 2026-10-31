"""スパイク 3：XML 取り込みで既存キューがどう扱われるかを試すための、テスト用 XML を作る。

使い方（ターミナルで）:
    python3 scripts/spikes/spike3_make_import_xml.py <エクスポートした XML> <出力する XML>

やること:
    1. Rekordbox からエクスポートしたコレクションの XML を読む（読み取りのみ）
    2. ファイル名に "spike3-" を含むテスト用の 4 曲だけを取り出す
    3. 曲ごとに「既存と同じ位置」「違う位置」「既存にあるが XML には書かない」キューを混ぜて、
       取り込み用の XML を書き出す

標準ライブラリだけで動くので、pip install や仮想環境（venv）は要らない。
Rekordbox の DB（master.db）には一切触れない。
"""

# Python の慣習メモ:
# - import は TypeScript の import と同じ。xml.etree.ElementTree は標準の XML パーサー
# - 型ヒント（`def f(x: float) -> str:`）は TypeScript の型注釈に近いが、実行時には検査されない
import sys
import xml.etree.ElementTree as ET

# Rekordbox XML の POSITION_MARK の Num 属性：-1 がメモリーキュー、0〜7 がホットキュー A〜H
MEMORY = -1
HOT_A, HOT_B, HOT_H = 0, 1, 7


def bar_to_sec(track: ET.Element, bar: int) -> float:
    """小節番号（1 始まり）を秒に直す。

    TEMPO 要素の先頭（最初の拍の位置 Inizio と BPM）から計算する。
    テスト用のデモ曲は BPM が一定なので、最初の TEMPO だけで足りる。
    """
    tempo = track.find("TEMPO")  # 最初に見つかった子要素（なければ None）
    if tempo is None:
        raise SystemExit(f"TEMPO がありません（解析前？）: {track.get('Location')}")
    first_beat = float(tempo.get("Inizio"))
    sec_per_bar = 4 * 60 / float(tempo.get("Bpm"))  # 4/4 拍子を前提にする
    return first_beat + (bar - 1) * sec_per_bar


def existing_marks(track: ET.Element) -> list[dict]:
    """エクスポートに入っている既存のキューを {num, start} の辞書のリストで返す。"""
    # リスト内包表記：[式 for 変数 in 反復可能] は TS の array.map(...) に相当
    return [
        {"num": int(m.get("Num")), "start": float(m.get("Start"))}
        for m in track.findall("POSITION_MARK")
    ]


def find_mark(marks: list[dict], num: int) -> dict:
    """指定した Num の最初のキューを返す。オーナーの準備が足りなければ分かるように止める。"""
    for m in marks:
        if m["num"] == num:
            return m
    raise SystemExit(f"Num={num} のキューが見つかりません。手順 2 のキューを打ったか確認してください")


def make_track(src: ET.Element, minimal: bool) -> ET.Element:
    """取り込み用の TRACK 要素を作る。

    minimal=False：エクスポートの属性（曲名、BPM など）と TEMPO（ビートグリッド）をそのまま写す
    minimal=True ：TrackID・Name・Location だけにする（足りない情報が消されるかを見るため）
    既存の POSITION_MARK は写さない。キューは呼び出し側で決めて足す
    """
    if minimal:
        attrs = {k: src.get(k) for k in ("TrackID", "Name", "Location")}
    else:
        attrs = dict(src.attrib)  # 属性を全部コピー
    track = ET.Element("TRACK", attrs)
    if not minimal:
        for tempo in src.findall("TEMPO"):
            track.append(tempo)
    return track


def add_mark(track: ET.Element, num: int, start: float, name: str) -> None:
    """POSITION_MARK を 1 つ足す。Type="0" は普通のキュー（ループではない）。"""
    ET.SubElement(
        track,
        "POSITION_MARK",
        {"Name": name, "Type": "0", "Start": f"{start:.3f}", "Num": str(num)},
    )


def build(src_tracks: dict[str, ET.Element]) -> tuple[ET.Element, list[str]]:
    """4 曲ぶんの TRACK を作り、何を書いたかの説明（ログ）も返す。"""
    out: list[ET.Element] = []
    log: list[str] = []

    # A：キューなしの曲 → 新しいキューが入るか（基準になるケース）
    s = src_tracks["A"]
    t = make_track(s, minimal=False)
    add_mark(t, MEMORY, bar_to_sec(s, 17), "xml-mem-bar17")
    add_mark(t, HOT_A, bar_to_sec(s, 33), "xml-hotA-bar33")
    out.append(t)
    log.append(f"A: メモリー @{bar_to_sec(s, 17):.3f}s（17 小節目）, ホット A @{bar_to_sec(s, 33):.3f}s（33 小節目）を追加")

    # B：メモリーキュー 2 つ（1 つ目・2 つ目）がある曲
    #    1 つ目と同じ位置 → 重複するか／2 つ目は書かない → 消えるか／新しい位置 → 追加されるか
    s = src_tracks["B"]
    mems = sorted((m for m in existing_marks(s) if m["num"] == MEMORY), key=lambda m: m["start"])
    if len(mems) < 2:
        raise SystemExit("B の曲にメモリーキューを 2 つ打ってください")
    t = make_track(s, minimal=False)
    add_mark(t, MEMORY, mems[0]["start"], "xml-mem-same")
    new_pos = bar_to_sec(s, 49)  # 既存のキュー（9・25 小節目）と重ならない位置
    add_mark(t, MEMORY, new_pos, "xml-mem-new")
    out.append(t)
    log.append(
        f"B: 既存メモリー @{mems[0]['start']:.3f}s と同じ位置に 1 つ, 新しい位置 @{new_pos:.3f}s に 1 つ。"
        f"既存メモリー @{mems[1]['start']:.3f}s は XML に書かない"
    )

    # C：ホットキュー A・B・H がある曲
    #    A は違う位置 → 上書きか／B は同じ位置 → 重複か／H は書かない → 消えるか／新しいメモリーキュー
    s = src_tracks["C"]
    marks = existing_marks(s)
    a, b, h = find_mark(marks, HOT_A), find_mark(marks, HOT_B), find_mark(marks, HOT_H)
    t = make_track(s, minimal=False)
    # 移動先と新しいメモリーキューは、既存のキュー（9・25・41 小節目）と重ならない位置にする
    moved_a = bar_to_sec(s, 57)
    new_mem = bar_to_sec(s, 73)
    add_mark(t, HOT_A, moved_a, "xml-hotA-moved")
    add_mark(t, HOT_B, b["start"], "xml-hotB-same")
    add_mark(t, MEMORY, new_mem, "xml-mem-new")
    out.append(t)
    log.append(
        f"C: ホット A を @{a['start']:.3f}s → @{moved_a:.3f}s に移動, ホット B は同じ @{b['start']:.3f}s, "
        f"ホット H（@{h['start']:.3f}s）は書かない, メモリー @{new_mem:.3f}s を追加"
    )

    # D：ホットキュー A がある曲を、属性を最小限にして取り込む
    #    → 曲名以外の情報（BPM、アーティスト、グリッドなど）や既存キューが消えるか
    s = src_tracks["D"]
    t = make_track(s, minimal=True)
    add_mark(t, MEMORY, bar_to_sec(s, 17), "xml-mem-bar17")
    out.append(t)
    log.append(f"D: TrackID・Name・Location だけ + メモリー @{bar_to_sec(s, 17):.3f}s。ホット A と TEMPO は書かない")

    return out, log


def main() -> None:
    # sys.argv はコマンドライン引数のリスト（[0] はスクリプト自身）。TS の process.argv に近い
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    export_path, out_path = sys.argv[1], sys.argv[2]

    root = ET.parse(export_path).getroot()  # 読み取りのみ。元のファイルは変更しない
    src_tracks: dict[str, ET.Element] = {}
    for tr in root.iter("TRACK"):
        loc = tr.get("Location") or ""
        for key in "ABCD":
            if f"spike3-{key}-" in loc and tr.get("TrackID"):  # 曲の本体（TrackID 付き）だけ拾う
                src_tracks[key] = tr
    missing = [k for k in "ABCD" if k not in src_tracks]
    if missing:
        raise SystemExit(f"エクスポートに見つからない曲: {missing}（コレクションに追加してからエクスポートしましたか？）")

    tracks, log = build(src_tracks)

    # キューが曲の長さ（TotalTime、秒）を超えていたら、テストとして意味がないので知らせる
    for key, t in zip("ABCD", tracks):  # zip は 2 つのリストを並べて 1 組ずつ取り出す
        total = float(src_tracks[key].get("TotalTime") or "inf")
        for m in t.findall("POSITION_MARK"):
            if float(m.get("Start")) >= total:
                print(f"注意: {key} のキュー {m.get('Name')} が曲の長さ {total:.0f}s を超えています")

    # 取り込み用 XML の骨組み。PLAYLISTS にテスト用プレイリストを 1 つ入れ、
    # 「曲単位の取り込み」と「プレイリスト単位の取り込み」の両方を試せるようにする
    doc = ET.Element("DJ_PLAYLISTS", {"Version": "1.0.0"})
    ET.SubElement(doc, "PRODUCT", {"Name": "cueing-bot-spike3", "Version": "0.0.0", "Company": ""})
    coll = ET.SubElement(doc, "COLLECTION", {"Entries": str(len(tracks))})
    for t in tracks:
        coll.append(t)
    playlists = ET.SubElement(doc, "PLAYLISTS")
    root_node = ET.SubElement(playlists, "NODE", {"Type": "0", "Name": "ROOT", "Count": "1"})
    pl = ET.SubElement(
        root_node, "NODE", {"Name": "spike3", "Type": "1", "KeyType": "0", "Entries": str(len(tracks))}
    )
    for t in tracks:
        ET.SubElement(pl, "TRACK", {"Key": t.get("TrackID")})

    ET.indent(doc)  # 人が読めるように字下げする
    ET.ElementTree(doc).write(out_path, encoding="UTF-8", xml_declaration=True)
    print("\n".join(log))
    print(f"書き出しました: {out_path}")


# このファイルを直接実行したときだけ main() を呼ぶ、という Python の定型句
if __name__ == "__main__":
    main()
