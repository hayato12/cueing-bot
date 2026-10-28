"""スパイク 3 の切り分け実験：Rekordbox がエクスポートした XML から 1 曲ぶんを「そのまま」切り出す。

使い方:
    python3 scripts/spikes/spike3c_extract_track.py <エクスポートした XML> <ファイル名の一部> <出力する XML>
    例: python3 scripts/spikes/spike3c_extract_track.py export.xml spike3-E- import.xml

ねらい:
    メモリーキューが 1 つしか取り込まれないのが、Rekordbox の仕様か、こちらの XML の書き方のせいかを見分ける。
    そのため、XML パーサーで読み直して書き出すのではなく、エクスポートの「文字列」から
    該当する <TRACK ...> 〜 </TRACK> をそのまま切り出す（属性の順番や書式も変えない）。
    全曲入りのエクスポートを取り込み用にそのまま使うと、3,000 曲の中から探すことになるので、1 曲だけにする。
"""

import re
import sys


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    export_path, name_part, out_path = sys.argv[1:]
    # with 文は、ブロックを抜けるとファイルを自動で閉じる（TS の try/finally で close するのに近い）
    with open(export_path, encoding="utf-8") as f:
        text = f.read()

    # 正規表現で COLLECTION 内の <TRACK ...>...</TRACK> を 1 つずつ取り出す。
    # re.S は「. が改行にも当たる」指定。.*? は最短一致（次の </TRACK> で止まる）
    blocks = [m.group(0) for m in re.finditer(r"<TRACK TrackID=.*?</TRACK>", text, re.S)]
    hits = [b for b in blocks if name_part in b]
    if len(hits) != 1:
        raise SystemExit(f"'{name_part}' を含む曲が {len(hits)} 曲見つかりました（1 曲にしてください）")
    track = hits[0]
    track_id = re.search(r'TrackID="(\d+)"', track).group(1)

    # ヘッダー（<?xml ...?> と PRODUCT）もエクスポートのものを使う
    header = text[: text.index("<COLLECTION")]
    out = (
        header
        + '<COLLECTION Entries="1">\n    '
        + track
        + "\n  </COLLECTION>\n"
        + '  <PLAYLISTS>\n    <NODE Type="0" Name="ROOT" Count="1">\n'
        + f'      <NODE Name="spike3c" Type="1" KeyType="0" Entries="1">\n        <TRACK Key="{track_id}"/>\n'
        + "      </NODE>\n    </NODE>\n  </PLAYLISTS>\n</DJ_PLAYLISTS>\n"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(track)
    print(f"書き出しました: {out_path}")


if __name__ == "__main__":
    main()
