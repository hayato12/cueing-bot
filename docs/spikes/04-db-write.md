# スパイク 4：master.db にキューを直接書けるか

状態：**完了**（2026-10-29〜30）。MP3（CBR）と M4A で、DB に直接書いたメモリーキューが Rekordbox で使えた。これを受けて [ADR 0001](../adr/0001-write-cues-to-master-db.md) で反映の方式を決めた。USB への書き出しと XDJ-RR での呼び出しも、2026-10-31 に確かめて問題なかった（下の「USB と XDJ-RR」）。

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
5. **クラウドライブラリ同期。** オンにしている場合、DB を直接書き換えるとどうなるか（オーナーは使っていない。2026-10-30 確認）

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
3. [scripts/spikes/spike4_write_cues.py](../../scripts/spikes/spike4_write_cues.py) で、E と F にメモリーキューを 3 つずつ書く。下調べで分かった Rekordbox と同じ形（`djmdCue`・`contentCue`・`CueUpdated`・USN）で書く。引数なしなら表示だけ、`--execute` でバックアップを取ってから書く（手順 2 のバックアップもスクリプトが行う）
4. Rekordbox を起動し、画面でキューの位置と、キューから再生したときの位置を確かめる
5. XML でエクスポートし、キューが入っているか確かめる
6. USB に書き出し、XDJ-RR でメモリーキューを呼び出せるか確かめる
7. おかしければ、Rekordbox を終了してバックアップに戻す

うまくいけば、VBR の MP3、FLAC、`contentCue` を書かない場合などに広げる。

## 結果

### 下調べ（2026-10-30、master.db のコピー）

[scripts/spikes/spike4_inspect_cues.py](../../scripts/spikes/spike4_inspect_cues.py) を、10/28 15:39 に取ったコピーで動かした（pyrekordbox 0.4.4、`repo/.venv`）。読み取りだけで、コピーの更新日時も変わっていない。出力は `~/llm/cueing-bot/data/spike4/inspect.txt`。

| 項目 | 結果 |
|---|---|
| 曲のファイルの種類 | 3,165 曲のうち **M4A が 2,535 曲**、MP3 が 412 曲、WAV が 140 曲、ほか（FileType 25 が 65、26 が 6、MP4 が 4、AIFF が 2、FLAC が 1） |
| `InFrame` | **8,446 行すべてで `floor(InMsec * 150 / 1000)`**（rbx の観察どおり） |
| MP3 の `InMpegFrame`・`InMpegAbs` | MP3 のキュー 1,421 行のうち **1,414 行が両方 0**。残り 7 行は `InMpegFrame` だけ値があり、どれも曲の頭から 0.2 秒以内のキュー（値は `InFrame` の半分ほど）。**0 で書けば Rekordbox 自身とほぼ同じ** |
| `contentCue` | キューのある曲 1,577 曲すべてに行がある（キューが 0 になった曲の行も 8 つ残っている）。JSON の要素数は **すべての曲で `djmdCue` の行数と一致**。行の ID は曲の UUID |
| JSON の形 | `djmdCue` の 1 行が 1 要素。`ID`・`ContentID`・`ContentUUID`・`InMsec`・`InFrame`・`InMpegFrame`・`InMpegAbs`・`OutMsec`・`OutFrame`・`OutMpegFrame`・`OutMpegAbs`・`Kind`・`Color`・`UUID`・`created_at`・`updated_at` は必ずある。`ColorTableIndex`・`ActiveLoop`・`BeatLoopSize`・`CueMicrosec`・`Comment` は値が NULL なら書かない（`Comment` は空文字でも書かない）。日時は `2026-10-28T14:25:01.621+00:00` の形 |
| 列の値の 2 つの型 | 画面で打ったキューの多く（ホット 3,518 行、メモリー 4,309 行）は `Color` が -1、`ColorTableIndex`・`ActiveLoop`・`Comment`・`BeatLoopSize`・`CueMicrosec` が NULL。XML で取り込んだキュー（スパイク 3 のテスト曲）は、それらが 0（`Color` は 255） |
| 共通 | `OutMsec` は -1（ループ以外）、`OutFrame`・`OutMpegFrame`・`OutMpegAbs` は 0。キューの行の `usn`・`rb_local_usn` は NULL、`rb_*` の状態の列は 0 |
| USN | テスト曲 E・F・G で、`contentCue.rb_local_usn` は `djmdContent.rb_local_usn` より 1 小さい（`contentCue` を書いてから曲の行を書いている）。`djmdContent.CueUpdated` はキューを変えるたびに増えている |
| メモリーキューの数 | 1 曲あたり最大 **10**（10 個の曲が 15 曲）。rbx の「10 個まで」と合う |

**分かったこと**

1. **MP3 の位置の列は、心配していたほどの問題ではない。** Rekordbox 自身が MP3 のキューのほぼすべてで `InMpegFrame`・`InMpegAbs` を 0 にしている。そもそもライブラリの 8 割は M4A
2. **キューを書くときは `djmdCue` と `contentCue` をそろえる必要がある。** Rekordbox 自身のデータでは、両者が全曲で一致している。djcues のように `djmdCue` だけを書くと、この一致が崩れる
3. 書き込みの形は、画面で打ったキュー（`Color` -1、任意の列は NULL）にそろえる。USN は「`contentCue` → 曲の行」の順に 1 ずつ進める。`CueUpdated` も増やす

### 書き込みの試験（2026-10-30、本物の master.db）

オーナーの OK のもと、[scripts/spikes/spike4_write_cues.py](../../scripts/spikes/spike4_write_cues.py) を実行した。事前に Rekordbox の「ライブラリのバックアップ」（zip、音楽ファイルは含めない）を取り、スクリプトも書く直前の master.db 一式を `data/db/backup-20261030-214855/` にコピーした。Rekordbox を終了し、止まっているのを確かめてから書いた。記録は `~/llm/cueing-bot/data/spike4/`（`dryrun.txt`・`write.txt`・`inspect-after.txt`）。

| 曲 | 書く前 | 書いたメモリーキュー |
|---|---|---|
| E（Demo Track 1、128 BPM） | メモリー 15.023s（スパイク 3 の 4 回目の取り込み） | 15.023s・45.023s・75.023s（9・25・41 小節目） |
| F（Demo Track 2、120 BPM） | キューなし | 16.024s・48.024s・80.024s（9・25・41 小節目） |

- エラーなく終わった。書いた後の DB のコピーを読むと、E・F とも `djmdCue` 3 行と `contentCue` の JSON 3 要素が一致。ライブラリ全体でも、`contentCue` と数が合わない曲・欠けている曲は 0
- `CueUpdated` は E が 9→15、F が 6→10。USN は `contentCue` → 曲の行の順に 1 ずつ進んだ
- **Rekordbox を起動すると、E・F の波形にメモリーキューが 3 つずつ出た**（オーナーの画面で確認）
- **それぞれのキューから再生すると、9・25・41 小節目の頭から鳴った。いつも使う曲 2〜3 曲のキューも変わっていなかった**（オーナーが確認）
- pyrekordbox が「プレイリスト 5 つが masterPlaylists6.xml にない」と警告した。照合の警告で、プレイリストには書いていない。masterPlaylists6.xml は Rekordbox の終了時に更新されていて、スクリプトのバックアップには入っていない（zip には入っている）

**まだ確かめていないこと**：USB への書き出しと XDJ-RR での呼び出し（オーナーが出先のため後日）、M4A・VBR の MP3 の曲

### M4A の曲（2026-10-30）

Demo Track 1（E）を macOS の `afconvert` で AAC 256kbps の M4A にしたコピー（`data/spike4/tracks/spike4-M4A-demo1.m4a`）を、コレクションに入れて解析した。キューは打たずに、同じスクリプトで `--target spike4-M4A-demo1` を付けて書いた（書く直前のバックアップは `data/db/backup-20261030-220331/`、記録は `data/spike4/*-m4a.txt`）。

- Rekordbox の解析では、最初の拍が 59ms。MP3 版（E）の 23ms より 36ms 後ろで、M4A の頭の無音（エンコーダーの遅延）のぶんがビートグリッドに入っているとみられる
- キューはこのグリッドに合わせて 15.059s・45.059s・75.059s（9・25・41 小節目）に書いた。エラーなし。`djmdCue` 3 行と `contentCue` の JSON が一致、ライブラリ全体の食い違いも 0
- **画面にメモリーキューが 3 つ出て、それぞれから再生すると小節の頭から鳴った**（オーナーが確認）
- MPEG の列は MP3 と同じく 0。M4A でも位置は `InMsec`（と `InFrame`）だけで決まっているとみられる

**まだ確かめていないこと（更新）**：USB への書き出しと XDJ-RR での呼び出し、VBR の MP3、WAV・FileType 25/26 の曲

### ホットキュー（2026-10-30）

同じ M4A のテスト曲に、`--hot A=33 D=49 H=57` を付けて書いた（メモリーキュー 9・25・41 小節目も書き直し）。書く直前のバックアップは `data/db/backup-20261030-222622/`、記録は `data/spike4/*-hot.txt`。

- ホットキューは `Kind` でパッドを表す：A=1、D=5、H=9 で書いた。`Color` は -1、`ColorTableIndex` など任意の列は NULL（画面で打ったホットキューの多くと同じ形）
- エラーなし。`djmdCue` 6 行と `contentCue` の JSON 6 要素が一致、ライブラリ全体の食い違いも 0
- **A・D・H が正しいパッドに出て、色も Rekordbox の既定の色で付き、パッドを押すと小節の頭から鳴った**（オーナーが確認）。`Kind` の対応（A〜C が 1〜3、D〜H が 5〜9、4 は使わない）は正しい
- **気をつける点：Rekordbox 本体を終了しても、常駐の rekordboxAgent が master.db を開いていることがある。** 今回は終了の後に起動し直していて、`master.db-wal` に未反映の書き込みも残っていたので、書くのを止めて rekordboxAgent も終了してもらった。書く前は、rekordboxAgent も止まっていること、master.db を開いているプロセスがないこと（`lsof` など）を確かめる

これで、MVP の 4 つのキュー（メモリー 2 つ、ホット 2 つ）はどれも DB に直接書ける。

### USB と XDJ-RR（2026-10-31）

オーナーが、スパイク 4 で書いたテスト曲 3 曲（`spike3-E`・`spike3-F` の MP3、`spike4-M4A-demo1` の M4A）を Rekordbox から USB に書き出し、XDJ-RR の実機で確かめた。

- **問題なし**（オーナーの報告）。DB に直接書いたメモリーキューとホットキューが XDJ-RR で出て、位置も合っていた
- XDJ-RR の世代が読む旧い形式（`PCOB`）も、Rekordbox が書き出しのときに作っていると考えられる。USB の解析ファイルの中身は読んでいない
- これで ADR 0001 の「ここで問題が出たら見直す」の項目は解消した

