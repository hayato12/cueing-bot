"""スパイク 4：テスト用の曲だけに、メモリーキュー（とホットキュー）を master.db へ直接書く。

使い方:
    python3 scripts/spikes/spike4_write_cues.py            # 書かずに、書く内容を表示するだけ（既定）
    python3 scripts/spikes/spike4_write_cues.py --execute  # バックアップを取ってから書く
    python3 scripts/spikes/spike4_write_cues.py --target spike4-M4A-demo1  # 対象の曲を変える（ファイル名の一部、複数可）
    python3 scripts/spikes/spike4_write_cues.py --hot A=33 H=57  # ホットキューも書く（パッド=小節番号）

対象:
    既定ではスパイク 3 のテスト曲（デモ曲のコピー）の E と F だけ。ファイル名で探し、ほかの曲には触れない。
    --target を付けると、その名前を含む曲を対象にする（"spike" を含む名前だけ受け付ける。本番の曲に書かないため）。
    それぞれのキューを全部消して、メモリーキューを 9・25・41 小節目の 3 つにする。--hot を付けると、ホットキューも足す。

書き方（スパイク 4 の下調べで分かった、Rekordbox 自身の書き方にそろえる）:
    - djmdCue：画面で打ったキューと同じ形（Color=-1、任意の列は NULL、InFrame=floor(ms*150/1000)、MPEG の列は 0）
    - ホットキューは Kind でパッドを表す（A〜C が 1〜3、D〜H が 5〜9。4 は使わない）。色は画面で打ったものと同じく Color=-1
    - contentCue：その曲の全キューの JSON を書き直す（NULL の列はキーごと書かない）
    - djmdContent.CueUpdated を増やし、USN を「contentCue → djmdContent」の順に 1 ずつ進める

安全のための決めごと:
    - Rekordbox の起動中は書かない（pyrekordbox も commit を止める）
    - --execute のときは、書く前に master.db と -wal・-shm を ~/llm/cueing-bot/data/db/backup-日時/ にコピーする
    - 戻すときは、Rekordbox を終了してから、バックアップの 3 つのファイルを元の場所に戻す
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6 import tables

TARGETS = ("spike3-E-multi", "spike3-F-samepos")
BARS = (9, 25, 41)
HOT_KIND = {"A": 1, "B": 2, "C": 3, "D": 5, "E": 6, "F": 7, "G": 8, "H": 9}
BACKUP_ROOT = Path.home() / "llm/cueing-bot/data/db"


def bar_to_ms(first_beat_ms: float, bpm: float, bar: int) -> int:
    """小節番号（1 始まり）をミリ秒にする。テスト曲は BPM が一定なので、最初の拍と BPM から計算できる。"""
    return round(first_beat_ms + (bar - 1) * 4 * 60_000 / bpm)


def first_beat_ms(db: Rekordbox6Database, content) -> float:
    """解析ファイル（ANLZ の .DAT）のビートグリッドから、最初の拍の位置を読む。"""
    for path, anlz in db.read_anlz_files(content).items():
        if path.suffix == ".DAT":
            for tag in anlz.tags:
                if type(tag).__name__ == "PQTZAnlzTag":
                    return float(tag.get_times()[0]) * 1000
    raise SystemExit(f"ビートグリッドが読めません: {content.FolderPath}")


def json_time(dt: datetime) -> str:
    """contentCue の JSON の日時の形（例：2026-10-28T14:25:01.621+00:00）にする。"""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def cue_json(cue) -> dict:
    """djmdCue の 1 行を、contentCue の JSON の 1 要素にする。Rekordbox と同じく、NULL・空の任意の列は書かない。"""
    out = {
        "ID": cue.ID, "ContentID": cue.ContentID, "ContentUUID": cue.ContentUUID,
        "InMsec": cue.InMsec, "InFrame": cue.InFrame, "InMpegFrame": cue.InMpegFrame, "InMpegAbs": cue.InMpegAbs,
        "OutMsec": cue.OutMsec, "OutFrame": cue.OutFrame, "OutMpegFrame": cue.OutMpegFrame, "OutMpegAbs": cue.OutMpegAbs,
        "Kind": cue.Kind, "Color": cue.Color,
    }
    for key in ("ColorTableIndex", "ActiveLoop", "Comment", "BeatLoopSize", "CueMicrosec"):
        value = getattr(cue, key)
        if value is not None and value != "":
            out[key] = value
    out["UUID"] = cue.UUID
    out["created_at"] = json_time(cue.created_at)
    out["updated_at"] = json_time(cue.updated_at)
    return out


def backup(db_dir: Path) -> Path:
    dest = BACKUP_ROOT / f"backup-{datetime.now():%Y%m%d-%H%M%S}"
    dest.mkdir(parents=True)
    for name in ("master.db", "master.db-wal", "master.db-shm"):
        src = db_dir / name
        if src.exists():
            shutil.copy2(src, dest / name)  # copy2 は更新日時もそのまま写す
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="実際に書く（指定しなければ表示だけ）")
    parser.add_argument("--target", nargs="+", default=list(TARGETS), help="対象の曲のファイル名の一部")
    parser.add_argument("--hot", nargs="*", default=[], help="ホットキュー。パッド=小節番号（例：A=33 H=57）")
    args = parser.parse_args()
    hot = []  # (Kind, 小節番号)
    for item in args.hot:
        pad, _, bar = item.partition("=")
        if pad.upper() not in HOT_KIND or not bar.isdigit():
            raise SystemExit(f"--hot の書き方が違います: {item}（例：A=33）")
        hot.append((HOT_KIND[pad.upper()], int(bar)))
    if any("spike" not in t for t in args.target):
        raise SystemExit("--target にはテスト用の曲（名前に spike を含む）だけを指定してください")

    db = Rekordbox6Database()  # 本物の master.db（場所は pyrekordbox が Rekordbox の設定から見つける）
    print(f"DB: {db.db_directory / 'master.db'}")

    plans = []
    for target in args.target:
        hits = [c for c in db.get_content() if target in (c.FolderPath or "")]
        if len(hits) != 1:
            raise SystemExit(f"'{target}' の曲が {len(hits)} 曲見つかりました（1 曲のはず）")
        content = hits[0]
        fb = first_beat_ms(db, content)
        bpm = content.BPM / 100
        # (Kind, ミリ秒)。Kind 0 がメモリーキュー
        positions = [(0, bar_to_ms(fb, bpm, b)) for b in BARS] + [(k, bar_to_ms(fb, bpm, b)) for k, b in hot]
        existing = list(db.get_cue(ContentID=content.ID))
        print(f"\n{target}  ID={content.ID}  BPM={content.BPM / 100}  最初の拍={fb:.0f}ms")
        print(f"  消すキュー: {[(c.Kind, c.InMsec) for c in existing]}")
        print(f"  書くキュー (Kind, ms): {positions}")
        plans.append((content, existing, positions))

    if not args.execute:
        print("\n表示だけで終わります（書くときは --execute を付ける）")
        return

    print(f"\nバックアップ: {backup(db.db_directory)}")
    now = datetime.now(timezone.utc)
    used_ids: set[str] = set()
    for content, existing, positions in plans:
        for cue in existing:
            db.delete(cue)
        new_cues = []
        for kind, ms in positions:
            # Rekordbox のキューの ID は 32 ビットの乱数（例：2625852351）。同じ実行の中での重複も避ける
            cue_id = str(db.generate_unused_id(tables.DjmdCue, is_28_bit=False))
            while cue_id in used_ids:
                cue_id = str(db.generate_unused_id(tables.DjmdCue, is_28_bit=False))
            used_ids.add(cue_id)
            cue = tables.DjmdCue.create(
                ID=cue_id,
                ContentID=str(content.ID),
                ContentUUID=content.UUID,
                UUID=str(uuid4()),
                InMsec=ms, InFrame=ms * 150 // 1000, InMpegFrame=0, InMpegAbs=0,
                OutMsec=-1, OutFrame=0, OutMpegFrame=0, OutMpegAbs=0,
                Kind=kind, Color=-1,
                ColorTableIndex=None, ActiveLoop=None, Comment=None, BeatLoopSize=None, CueMicrosec=None,
                created_at=now, updated_at=now,
            )
            db.add(cue)
            new_cues.append(cue)

        cc = db.get_content_cue(ContentID=content.ID).one_or_none()
        if cc is None:
            cc = tables.ContentCue.create(ID=content.UUID, ContentID=str(content.ID), UUID=str(uuid4()))
            db.add(cc)
        cc.Cues = json.dumps([cue_json(c) for c in sorted(new_cues, key=lambda c: c.InMsec)], separators=(",", ":"))
        cc.rb_cue_count = len(new_cues)
        # CueUpdated は文字列の列（中身は数）。消した数と足した数だけ増やす（rbx の観察：キュー 1 つの変更で 1）
        content.CueUpdated = str(int(content.CueUpdated or 0) + len(existing) + len(new_cues))

        # USN：Rekordbox と同じく contentCue → 曲の行の順に 1 ずつ進める。キューの行は NULL のまま
        cc.rb_local_usn = db.increment_local_usn()
        content.rb_local_usn = db.increment_local_usn()

    db.commit(autoinc=False)  # USN は上で手で進めたので、pyrekordbox の自動の加算は使わない
    print("書きました。Rekordbox を起動して確かめてください")


if __name__ == "__main__":
    sys.exit(main())
