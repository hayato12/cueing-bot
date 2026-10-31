"""本物のライブラリ（master.db のコピーと解析ファイル）を読むテスト。Mac だけで回す。

CUEING_BOT_TEST_PLAYLIST=<プレイリスト名> uv run pytest -m personal_data
"""

import os
from pathlib import Path

import pytest

from cueing_bot import config

pytestmark = pytest.mark.personal_data

PLAYLIST = os.environ.get("CUEING_BOT_TEST_PLAYLIST", "")


@pytest.mark.skipif(not PLAYLIST, reason="CUEING_BOT_TEST_PLAYLIST が未設定")
def test_reads_a_playlist_from_a_copy(tmp_path: Path) -> None:
    from cueing_bot.library.reader import open_library

    real_db = config.rekordbox_dir() / "master.db"
    mtime_before = real_db.stat().st_mtime_ns
    with open_library(config.rekordbox_dir(), tmp_path) as lib:
        ids = lib.track_ids_in_playlist(PLAYLIST)
        assert ids
        track = lib.track_input(ids[0])
        assert track.beats
        assert all(b.beat_in_bar in (1, 2, 3, 4) for b in track.beats)
        lib.existing_cues(ids[0])
        copy_dir = lib.snapshot.directory
    assert not copy_dir.exists()
    assert real_db.stat().st_mtime_ns == mtime_before  # 本物には触れていない
