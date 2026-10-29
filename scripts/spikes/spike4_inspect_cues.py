"""スパイク 4（DB にキューを書く）の下調べ：Rekordbox 自身がキューをどう DB に書いているかを、master.db のコピーから読む。

使い方:
    python3 scripts/spikes/spike4_inspect_cues.py <master.db のコピー>
    例: python3 scripts/spikes/spike4_inspect_cues.py ~/llm/cueing-bot/data/db/master.db

読み取りだけ。コピーを開き、何も書かない（commit しない）。本物の master.db は開かない。
pyrekordbox 0.4.4（スパイク 2 と同じ）で動かす。

調べること（DB に書くとき、Rekordbox と同じ形にするため）:
    1. 曲のファイルの種類（MP3 が多いと、MPEG のフレーム位置の列が問題になる）
    2. djmdCue の列ごとに、値が NULL か・0 か・それ以外か（ホットキューとメモリーキューで分けて）
    3. InFrame が floor(InMsec * 150 / 1000) になっているか（他のツールの観察）
    4. MP3 の InMpegFrame・InMpegAbs が InMsec とどう対応しているか
    5. contentCue（曲ごとのキューの JSON）がすべての曲にあるか、djmdCue と数が合うか、JSON の形
    6. 1 曲あたりのメモリーキューの最大数
    7. スパイク 3 のテスト曲のキューの行をそのまま出す（書き込みの見本にする）
"""

import json
import sys
from collections import Counter, defaultdict

# pyrekordbox は Rekordbox の DB を読むライブラリ。0.4.4 ではクラス名が Rekordbox6Database（7 にも使える）
from pyrekordbox import Rekordbox6Database

CUE_COLUMNS = [
    "InMsec", "InFrame", "InMpegFrame", "InMpegAbs", "OutMsec", "OutFrame", "OutMpegFrame",
    "OutMpegAbs", "Kind", "Color", "ColorTableIndex", "ActiveLoop", "Comment", "BeatLoopSize",
    "CueMicrosec", "InPointSeekInfo", "OutPointSeekInfo", "ContentUUID", "usn", "rb_local_usn",
    "rb_local_deleted", "rb_data_status", "rb_local_data_status", "rb_local_synced",
]


def shape(v) -> str:
    """値を「NULL」「0」「-1」「その他」にまとめる。列の使われ方を見るため。"""
    if v is None:
        return "NULL"
    if v in (0, "0", ""):
        return "0/空"
    if v in (-1, "-1"):
        return "-1"
    return "その他"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    db = Rekordbox6Database(path=sys.argv[1])

    contents = {c.ID: c for c in db.get_content()}
    print(f"曲: {len(contents)}")
    # FileType は数値（1=MP3, 4=M4A, 5=FLAC, 11=WAV, 12=AIFF など）
    print("ファイルの種類:", dict(Counter(c.FileType for c in contents.values())))

    cues = list(db.get_cue())
    print(f"\ndjmdCue: {len(cues)} 行")
    # 列によっては pyrekordbox 0.4.4 のモデルにないものがあるので getattr で読む
    cols = [c for c in CUE_COLUMNS if hasattr(cues[0], c)]
    for group, rows in (("ホット", [c for c in cues if c.Kind and c.Kind > 0]), ("メモリー", [c for c in cues if c.Kind == 0])):
        print(f"\n[{group}キュー {len(rows)} 行] 列ごとの値の内訳")
        for col in cols:
            print(f"  {col:16s}", dict(Counter(shape(getattr(r, col)) for r in rows)))

    in_frame_ok = sum(1 for c in cues if c.InFrame is not None and c.InMsec is not None and c.InFrame == c.InMsec * 150 // 1000)
    print(f"\nInFrame == floor(InMsec*150/1000): {in_frame_ok} / {len(cues)}")

    # MP3 の曲のキューで、InMpegFrame を InMsec から計算した値（44.1kHz、1 フレーム 1152 サンプル）と比べる
    mp3 = [c for c in cues if contents.get(c.ContentID) is not None and contents[c.ContentID].FileType == 1]
    by_shape = Counter((shape(c.InMpegFrame), shape(c.InMpegAbs)) for c in mp3)
    print(f"\nMP3 のキュー {len(mp3)} 行。(InMpegFrame, InMpegAbs) の内訳: {dict(by_shape)}")
    near = 0
    samples = []
    for c in mp3:
        if c.InMpegFrame and c.InMsec:
            est = c.InMsec * 44.1 / 1152
            if abs(c.InMpegFrame - est) <= 2:
                near += 1
            if len(samples) < 8:
                ct = contents[c.ContentID]
                samples.append((ct.BitRate, ct.SampleRate, c.InMsec, c.InFrame, c.InMpegFrame, c.InMpegAbs))
    print(f"  InMpegFrame ≒ InMsec*44.1/1152（±2）: {near}")
    print("  例 (BitRate, SampleRate, InMsec, InFrame, InMpegFrame, InMpegAbs):")
    for s in samples:
        print("   ", s)

    # 1 曲あたりのメモリーキューの数
    mem_per = Counter(c.ContentID for c in cues if c.Kind == 0)
    print(f"\n1 曲あたりのメモリーキュー: 最大 {max(mem_per.values()) if mem_per else 0}、分布 {dict(sorted(Counter(mem_per.values()).items()))}")

    # contentCue：曲ごとのキューの JSON
    ccs = list(db.get_content_cue())
    print(f"\ncontentCue: {len(ccs)} 行。djmdCue のある曲: {len({c.ContentID for c in cues})} 曲")
    cue_count = Counter(c.ContentID for c in cues)
    mismatch = 0
    keys = Counter()
    for cc in ccs:
        try:
            arr = json.loads(cc.Cues or "[]")
        except json.JSONDecodeError:
            mismatch += 1
            continue
        if len(arr) != cue_count.get(cc.ContentID, 0):
            mismatch += 1
        for e in arr:
            keys.update(e.keys())
    print(f"  JSON の要素数が djmdCue の数と合わない行: {mismatch}")
    print(f"  JSON の要素が持つキー（出てきた回数）: {dict(keys)}")
    no_cc = {c.ContentID for c in cues} - {cc.ContentID for cc in ccs}
    print(f"  djmdCue はあるのに contentCue がない曲: {len(no_cc)}")

    # スパイク 3 のテスト曲：行をそのまま出す
    print("\n--- スパイク 3 のテスト曲 ---")
    cc_by = {cc.ContentID: cc for cc in ccs}
    for ct in contents.values():
        if "spike3-" not in (ct.FolderPath or ""):
            continue
        print(f"\n{ct.FolderPath.rsplit('/', 1)[-1]}  ID={ct.ID} UUID={ct.UUID} CueUpdated={getattr(ct, 'CueUpdated', '?')} rb_local_usn={ct.rb_local_usn}")
        for c in sorted((c for c in cues if c.ContentID == ct.ID), key=lambda c: (c.Kind, c.InMsec)):
            print("   ", {col: getattr(c, col) for col in ["ID", "UUID", *cols]})
        if ct.ID in cc_by:
            cc = cc_by[ct.ID]
            print(f"    contentCue ID={cc.ID} rb_cue_count={cc.rb_cue_count} rb_local_usn={cc.rb_local_usn}")
            print("    Cues JSON:", cc.Cues)

    db.close()


if __name__ == "__main__":
    main()
