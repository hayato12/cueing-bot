# スパイク 3：XML を取り込んだとき既存のキューがどう扱われるか

状態：**実施中**（準備まで完了。Rekordbox での操作待ち）

## 問い

アプリが出力した XML を Rekordbox に取り込むと、曲にもともとあるキューは消えるのか、残るのか、重複するのか。

## 環境

| 項目 | 内容 |
|---|---|
| マシン | MacBook Pro M4 / 16GB |
| Rekordbox | 7（細かいバージョンは結果記入時に書く） |
| Python | 3.10（pyenv）。スクリプトは標準ライブラリだけなので venv も不要。環境管理ツールは未決定のまま |

## テスト用の曲

Rekordbox 付属のデモ曲（`~/Music/PioneerDJ/Demo Tracks/`）をコピーして使う。個人の曲を使わずに済み、本番の曲に影響しない。
コピー先は `~/llm/cueing-bot/data/spike3/tracks/`（リポジトリの外）。最初は `~/Music/cueing-bot-spike3/` に置いていたため、Rekordbox に登録したパスと XML の Location はそちらのまま。`~/Music/cueing-bot-spike3` は新しい場所へのシンボリックリンクにしてある。

| 曲 | 元の曲 | 取り込み前に手で打つキュー | XML に書くキュー | 確かめること |
|---|---|---|---|---|
| A `spike3-A-nocue` | Demo Track 1 | なし | メモリー（17 小節目）、ホット A（33 小節目） | 新しいキューが入るか（基準） |
| B `spike3-B-memory` | Demo Track 2 | メモリー（9・25 小節目） | メモリー 9 小節目（同じ位置）、49 小節目（新しい位置）。25 小節目は書かない | 同じ位置は重複するか／書かなかったキューは消えるか／新しいキューは足されるか |
| C `spike3-C-hotcue` | Demo Track 1 | ホット A（9）、B（25）、H（41） | ホット A を 57 小節目に移動、B は同じ位置、H は書かない、メモリー 73 小節目 | 同じ番号のホットキューは上書きか／書かなかったホットキューは消えるか |
| D `spike3-D-minimal` | Demo Track 2 | ホット A（9） | TrackID・Name・Location とメモリー 17 小節目だけ（BPM・アーティスト・TEMPO なし） | XML に書かなかった曲の情報（BPM、グリッドなど）が消えるか |

## 手順

1. 曲 A〜D をコレクションに追加して解析し、上の表どおりにキューを打つ
2. コレクションを XML でエクスポートする（`export.xml`、リポジトリの外に置く）
3. [scripts/spikes/spike3_make_import_xml.py](../../scripts/spikes/spike3_make_import_xml.py) で取り込み用の `import.xml` を作る
4. 1 回目：`rekordbox xml` の画面で曲 A〜D を 1 曲ずつ選び「コレクションにインポート」。終わったらエクスポート（`after1.xml`）
5. 2 回目：同じ XML のプレイリスト `spike3` を「プレイリストをインポート」。終わったらエクスポート（`after2.xml`）。同じ XML を 2 回取り込んだときに重複するか、取り込み方で違うかを見る
6. `export.xml`・`after1.xml`・`after2.xml` のキューを比べる

## 結果

（記入待ち）

## 結論と設計への影響

（記入待ち）
