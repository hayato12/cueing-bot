# スパイク 4：master.db にキューを直接書けるか

状態：**調査中**（2026-10-29〜）。既存ツールの調査が済み、下調べのスクリプトを用意した段階。

## 背景

スパイク 3 で、XML の取り込みでは 1 曲にメモリーキューを 1 つしか入れられないと分かった（Rekordbox 7.2.18。[03-xml-import.md](03-xml-import.md)）。
そこで、オーナーが **「DB への直接書き込みを OK とする」を仮決定**にした（2026-10-29）。CLAUDE.md の「DB に書き込まない」という約束を見直すかどうかは、このスパイクの結果を見て ADR で決める。それまで CLAUDE.md は変えない。

## 問い

1. Rekordbox 7.2.18 の master.db にメモリーキューを複数書き込んで、Rekordbox の画面と XDJ-RR で正しく使えるか
2. ライブラリを壊さずに書くには、何に気をつければよいか（書く列、一緒に更新する表、バックアップと戻し方）

## 既存のツールから分かったこと

| ツール | 書き方 | 分かること |
|---|---|---|
| [djcues](https://github.com/mcroydon/djcues)（Python、2026-04） | pyrekordbox で `djmdCue` に行を足す。ホット 8 個・メモリー 8 個 | ホットキューの `Kind` は A〜C が 1〜3、D〜H が 5〜9（4 は飛ばす）。書く前に master.db を自動でバックアップし、Rekordbox の起動中は書かない。`--dry-run` あり。**`contentCue` は更新していない。** MPEG の列（`InMpegFrame`・`InMpegAbs`）は 0 で書いている。対応バージョンの記載なし |
| [rbx](https://github.com/takayamaki/rbx)（Rust、[PR #7](https://github.com/takayamaki/rbx/pull/7)） | `djmdCue` の行、曲ごとの `contentCue` の行（その曲の全キューの JSON）、`djmdContent.CueUpdated` を一緒に書く | 実際の Rekordbox 7 の DB（キュー 28,883 行）と照らした結果：`InFrame` は `floor(InMsec * 150 / 1000)`。普通のキューでは `CueMicrosec`・`ActiveLoop`・`BeatLoopSize`・`ColorTableIndex`・`Comment` は NULL。キューのある曲には必ず `contentCue` の行が 1 つあり、キューが 0 になったら行を消す。キューを変えると `CueUpdated` が 1 つ増え、`contentCue` と `djmdContent` の USN が進む。メモリーキューは 1 曲 10 個まで。**MP3 と FLAC は対応していない**（ファイルの中の位置、VBR の MP3 なら MPEG フレームの位置も保存しているため） |
| [CueGen](https://github.com/mganss/cuegen)（C#、Rekordbox 6） | `djmdCue` に行を足し、`contentCue` の JSON も更新する | `contentCue` を一緒に直す必要がある、という点で rbx と同じ |
| [pyrekordbox](https://github.com/dylanljones/pyrekordbox)（[議論 #113](https://github.com/dylanljones/pyrekordbox/discussions/113)） | キュー専用の書き込み機能はない（表に行を足すことはできる）。`commit()` は Rekordbox の起動中なら止まり、USN を自動で進める | 作者いわく「キューを足すのはほとんどの曲で簡単だが、VBR・ABR の MP3 は `InMpegAbs` を再現できず止まっている」。0.5.0（2026-10）は Python 3.11 以上 |
| [seabass の issue #33](https://github.com/sebasje/seabass/issues/33) | — | USB に書き出す解析ファイル（ANLZ）には、キューの一覧が新旧 2 種類ある（旧 `PCOB`、新 `PCO2`）。XDJ-RX2 世代のプレーヤーは旧い方を読む。XDJ-RR も同じ世代なので、USB への書き出しで Rekordbox が両方を作り直すかを確かめる必要がある |

### 気になる点（このスパイクで確かめる）

1. **MP3 の位置の列。** オーナーのライブラリは MP3 が多いと考えられる。`InMpegFrame`・`InMpegAbs` を 0 で書いたとき、Rekordbox が位置を正しく扱うか。CBR と VBR で違うか
2. **`contentCue` と USN。** djcues のように `djmdCue` だけを書くと、Rekordbox がどちらを正とするのか。画面の表示、XML のエクスポート、USB への書き出しで食い違わないか
3. **USB への書き出し（XDJ-RR）。** DB に書いたキューが、書き出した USB の解析ファイルに入り、XDJ-RR で使えるか
4. **戻し方。** 書く前の master.db（`-wal`・`-shm` を含む）のコピーに戻せば、元に戻るか
5. **クラウドライブラリ同期。** オンにしている場合、DB を直接書き換えるとどうなるか（オンかどうかをオーナーに確認する）

## 進め方

### 1. 下調べ（読み取りのみ。master.db のコピーを使う）

[scripts/spikes/spike4_inspect_cues.py](../../scripts/spikes/spike4_inspect_cues.py) で、Rekordbox 自身が書いたキューの行を調べる。
コピーは `~/llm/cueing-bot/data/db/`（スパイク 2 の追記で作ったもの。最新にするなら、Rekordbox を閉じてから取り直す）。

```sh
cd ~/llm/cueing-bot/repo
python3 scripts/spikes/spike4_inspect_cues.py ~/llm/cueing-bot/data/db/master.db
```

分かること：ファイルの種類の内訳、列ごとの値の使われ方（ホットとメモリー別）、`InFrame` の式、MP3 の `InMpegFrame`・`InMpegAbs` と `InMsec` の関係、`contentCue` の JSON の形と `djmdCue` との一致、スパイク 3 のテスト曲の行そのもの（書き込みの見本）。

### 2. 書き込みの試験（本物の master.db。実行の前にオーナーの OK を取る）

スパイク 3 のテスト曲（デモ曲のコピー、E と F）だけに書く。

1. Rekordbox を終了する
2. `master.db`・`master.db-wal`・`master.db-shm` を `~/llm/cueing-bot/data/db/backup-日時/` にコピーする（加えて、Rekordbox の「ライブラリのバックアップ」も取る）
3. スクリプトで、E と F にメモリーキューを 3 つずつ書く。下調べで分かった Rekordbox と同じ形（`djmdCue`・`contentCue`・`CueUpdated`・USN）で書く
4. Rekordbox を起動し、画面でキューの位置と、キューから再生したときの位置を確かめる
5. XML でエクスポートし、キューが入っているか確かめる
6. USB に書き出し、XDJ-RR でメモリーキューを呼び出せるか確かめる
7. おかしければ、Rekordbox を終了してバックアップに戻す

うまくいけば、VBR の MP3、FLAC、`contentCue` を書かない場合などに広げる。

## 結果

（未実施）
