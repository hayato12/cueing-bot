import shutil
from pathlib import Path

import pytest

from cueing_bot.library import snapshot as snapshot_mod
from cueing_bot.library.snapshot import SnapshotError, snapshot, take_snapshot


@pytest.fixture
def rb_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rekordbox"
    d.mkdir()
    (d / "master.db").write_bytes(b"db")
    (d / "master.db-wal").write_bytes(b"wal")
    (d / "master.db-shm").write_bytes(b"shm")
    (d / "masterPlaylists6.xml").write_text("<xml/>")
    return d


def ok(_: Path) -> bool:
    return True


def test_copies_db_and_side_files_without_touching_the_original(
    rb_dir: Path, tmp_path: Path
) -> None:
    before = {p.name: p.stat().st_mtime_ns for p in rb_dir.iterdir()}
    snap = take_snapshot(rb_dir, tmp_path / "work", ok)
    assert snap.db_path.read_bytes() == b"db"
    assert (snap.directory / "master.db-wal").read_bytes() == b"wal"
    assert (snap.directory / "masterPlaylists6.xml").exists()
    assert not (snap.directory / "master.db-shm").exists()  # -shm は写さない
    assert snap.attempts == 1
    assert {p.name: p.stat().st_mtime_ns for p in rb_dir.iterdir()} == before


def test_retries_when_the_original_changes_during_copy(
    rb_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real_copy = shutil.copy2

    def copy_and_write_once(src: Path, dst: Path) -> object:
        calls["n"] += 1
        if calls["n"] == 1:  # 1 回目のコピーの最中に Rekordbox が書いた、という状況
            (rb_dir / "master.db-wal").write_bytes(b"wal-changed")
        return real_copy(src, dst)

    monkeypatch.setattr(snapshot_mod.shutil, "copy2", copy_and_write_once)
    snap = take_snapshot(rb_dir, tmp_path / "work", ok, wait_s=0)
    assert snap.attempts == 2
    assert (snap.directory / "master.db-wal").read_bytes() == b"wal-changed"
    assert len(list((tmp_path / "work").iterdir())) == 1  # 失敗したコピーは消す


def test_gives_up_when_the_copy_never_passes_the_check(rb_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(SnapshotError):
        take_snapshot(rb_dir, tmp_path / "work", lambda _: False, attempts=2, wait_s=0)
    assert list((tmp_path / "work").iterdir()) == []


def test_missing_db_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        take_snapshot(tmp_path, tmp_path / "work", ok)


def test_context_manager_removes_the_copy(rb_dir: Path, tmp_path: Path) -> None:
    with snapshot(rb_dir, tmp_path / "work", ok) as snap:
        assert snap.db_path.exists()
    assert not snap.directory.exists()
    assert (rb_dir / "master.db").exists()


def test_shm_changes_do_not_block_the_copy(
    rb_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_copy = shutil.copy2

    def copy_and_touch_shm(src: Path, dst: Path) -> object:
        (rb_dir / "master.db-shm").write_bytes(b"shm-touched")  # Rekordbox が読むたびに変わる
        return real_copy(src, dst)

    monkeypatch.setattr(snapshot_mod.shutil, "copy2", copy_and_touch_shm)
    assert take_snapshot(rb_dir, tmp_path / "work", ok, wait_s=0).attempts == 1


def test_errors_during_copy_or_check_are_retried_and_cleaned_up(
    rb_dir: Path, tmp_path: Path
) -> None:
    calls = {"n": 0}

    def check(_: Path) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("file is not a database")
        return True

    snap = take_snapshot(rb_dir, tmp_path / "work", check, wait_s=0)
    assert snap.attempts == 2
    assert len(list((tmp_path / "work").iterdir())) == 1
