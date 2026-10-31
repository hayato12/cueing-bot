"""master.db のコピーを取る（ADR 0003）。

Rekordbox の起動中にコピーすると、`master.db` と `-wal` を写す間に書き込みが入り、組み合わせの合わない
コピーになることがある。そこで、コピーの前後でファイルの更新日時と大きさが変わっていないかを見て、
コピーを開いて整合性を確かめる。外れたらコピーし直す。

このモジュールは本物のファイルを**読むだけ**で、開かない（SQLite として接続しない）。
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DB_NAME = "master.db"
SIDE_FILES = ("master.db-wal",)
"""`-shm` は写さない。SQLite が開くときに `-wal` から作り直すうえ、Rekordbox が読むだけでも更新されるので、
前後の比べに入れるとコピーがいつまでも取れなくなる。"""
EXTRA_FILES = ("masterPlaylists6.xml",)
"""DB と一緒に写すファイル。pyrekordbox が DB と同じフォルダから読む。"""


class SnapshotError(RuntimeError):
    """何度コピーし直しても、整った組み合わせのコピーが取れなかった。"""


@dataclass(frozen=True)
class Snapshot:
    db_path: Path
    """コピーした master.db。"""
    directory: Path
    """コピーを置いたフォルダ。"""
    attempts: int
    """取れるまでに何回コピーしたか。"""
    seconds: float
    """コピーと確かめにかかった時間（ADR 0003 で「Sprint 0 で測る」としたもの）。"""


FileState = tuple[tuple[str, int, int], ...]


def _state(src_dir: Path) -> FileState:
    """コピーするファイルの名前・大きさ・更新日時（ns）。ないファイルは大きさ -1 にする。"""
    out: list[tuple[str, int, int]] = []
    for name in (DB_NAME, *SIDE_FILES, *EXTRA_FILES):
        p = src_dir / name
        if p.exists():
            st = p.stat()
            out.append((name, st.st_size, st.st_mtime_ns))
        else:
            out.append((name, -1, 0))
    return tuple(out)


def take_snapshot(
    src_dir: Path,
    dest_root: Path,
    check: Callable[[Path], bool],
    *,
    attempts: int = 3,
    wait_s: float = 1.0,
) -> Snapshot:
    """`src_dir` の master.db（と `-wal`・`masterPlaylists6.xml`）を `dest_root` の下にコピーする。

    `check` はコピーした master.db のパスを受け取り、開いて整合性（`PRAGMA quick_check`）を確かめる関数。
    暗号化された DB を開くのは pyrekordbox の仕事なので、ここでは受け取るだけにしている。
    """
    if not (src_dir / DB_NAME).is_file():
        raise FileNotFoundError(f"{DB_NAME} が見つかりません：{src_dir}")
    started = time.monotonic()
    for attempt in range(1, attempts + 1):
        dest = dest_root / f"db-copy-{datetime.now():%Y%m%d-%H%M%S-%f}"
        dest.mkdir(parents=True)
        try:
            before = _state(src_dir)
            for name, size, _ in before:
                if size >= 0:
                    shutil.copy2(src_dir / name, dest / name)
            after = _state(src_dir)
            good = before == after and check(dest / DB_NAME)
        except Exception:
            # コピーの最中に Rekordbox が -wal を消した、壊れたコピーを開けなかった、など。やり直す
            good = False
        if good:
            return Snapshot(dest / DB_NAME, dest, attempt, time.monotonic() - started)
        shutil.rmtree(dest, ignore_errors=True)
        if attempt < attempts:
            time.sleep(wait_s)
    raise SnapshotError(
        f"{attempts} 回コピーしても、整った master.db のコピーを取れませんでした。"
        "Rekordbox が書き込み中かもしれません。少し待ってからやり直してください。"
    )


@contextmanager
def snapshot(
    src_dir: Path,
    dest_root: Path,
    check: Callable[[Path], bool],
    *,
    keep: bool = False,
) -> Generator[Snapshot]:
    """`with` で使うと、抜けるときにコピーを消す（architecture.md 4 章「使い終わったら消す」）。"""
    snap = take_snapshot(src_dir, dest_root, check)
    try:
        yield snap
    finally:
        if not keep:
            shutil.rmtree(snap.directory, ignore_errors=True)
