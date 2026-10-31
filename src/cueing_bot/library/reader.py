"""master.db のコピーと解析ファイルから、`TrackInput` と `ExistingCues` を作る（ADR 0003）。

pyrekordbox には型が付いていないので、このモジュールの中だけで扱い、外には `model` の型だけを出す
（ADR 0002「境目で型を付けて包む」）。
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyrekordbox.anlz import AnlzFile  # pyright: ignore[reportMissingTypeStubs]
from pyrekordbox.masterdb import MasterDatabase  # pyright: ignore[reportMissingTypeStubs]
from sqlalchemy import text

from cueing_bot.library.grid import beats_from_pqtz, fingerprint, phrases_from_pssi
from cueing_bot.library.snapshot import Snapshot, snapshot
from cueing_bot.model import ExistingCue, ExistingCues, Phrase, TrackInput


class TrackReadError(RuntimeError):
    """1 曲を読めなかった。推定せずに「失敗」の一覧に出す（N9）。"""


@dataclass(frozen=True)
class PlaylistInfo:
    id: str
    name: str
    is_folder: bool


def _open_db(db_path: Path) -> Any:
    """コピーを開く。`db_dir` もコピーのフォルダにして、pyrekordbox が本物のフォルダに触れないようにする。"""
    return MasterDatabase(path=db_path, db_dir=db_path.parent)


def integrity_ok(db_path: Path) -> bool:
    """コピーを開いて `PRAGMA integrity_check` をかける。"""
    db = _open_db(db_path)
    try:
        rows = db.session.execute(text("PRAGMA integrity_check")).fetchall()
        return [tuple(r) for r in rows] == [("ok",)]
    finally:
        db.close()


class Library:
    """master.db のコピーを開いたもの。`open_library()` で作る。"""

    def __init__(self, db: Any, rekordbox_dir: Path, snap: Snapshot) -> None:
        self._db = db
        self._share = rekordbox_dir / "share"
        self.snapshot = snap

    # --- プレイリスト -------------------------------------------------------

    def playlists(self) -> list[PlaylistInfo]:
        out: list[PlaylistInfo] = []
        for pl in self._db.get_playlist().all():
            out.append(PlaylistInfo(str(pl.ID), str(pl.Name), bool(pl.is_folder)))
        return out

    def track_ids_in_playlist(self, name: str) -> list[str]:
        found = self._db.get_playlist(Name=name).all()
        if not found:
            raise KeyError(f"プレイリストが見つかりません：{name}")
        if len(found) > 1:
            raise KeyError(f"同じ名前のプレイリストが {len(found)} 個あります：{name}")
        return [str(c.ID) for c in self._db.get_playlist_contents(found[0]).all()]

    # --- 曲 ---------------------------------------------------------------

    def track_id_for_path(self, path: str) -> str | None:
        """音源のパスから曲の ID を引く。見つからなければ None。"""
        found = self._db.get_content(FolderPath=path).all()
        return str(found[0].ID) if len(found) == 1 else None

    def _content(self, track_id: str) -> Any:
        content = self._db.get_content(ID=track_id)
        if content is None:
            raise TrackReadError(f"曲が見つかりません：ID={track_id}")
        return content

    def _anlz_paths(self, content: Any) -> tuple[Path, Path]:
        rel = str(content.AnalysisDataPath or "").replace("\\", "/").strip("/")
        if not rel:
            raise TrackReadError(f"解析ファイルがありません：ID={content.ID}")
        dat = self._share / rel
        return dat, dat.with_suffix(".EXT")

    def track_input(self, track_id: str) -> TrackInput:
        """推定に渡す曲の情報を作る。既存のキューは読まない。"""
        content = self._content(track_id)
        dat, ext = self._anlz_paths(content)
        if not dat.is_file():
            raise TrackReadError(f"解析ファイル（DAT）がありません：ID={track_id}")
        try:
            dat_file: Any = AnlzFile.parse_file(dat)
            beat_in_bar, _bpms, times = dat_file.get_tag("PQTZ").get()
        except Exception as e:  # pyrekordbox が読めない解析ファイル（スパイク 2 で 11 曲）
            raise TrackReadError(f"PQTZ を読めません：ID={track_id}（{e}）") from e
        beats = beats_from_pqtz([int(b) for b in beat_in_bar], [float(t) for t in times])

        mood: int | None = None
        phrases: tuple[Phrase, ...] = ()
        if ext.is_file():
            try:
                ext_file: Any = AnlzFile.parse_file(ext)
                if "PSSI" in ext_file.tag_types:
                    pssi = ext_file.get_tag("PSSI").content
                    mood = int(pssi.mood)
                    entries = [(int(en.beat), int(en.kind)) for en in pssi.entries]
                    phrases = phrases_from_pssi(mood, entries, len(beats))
            except Exception as e:
                raise TrackReadError(f"PSSI を読めません：ID={track_id}（{e}）") from e

        path = str(content.FolderPath or "")
        audio = Path(path)
        if not audio.is_file():
            raise TrackReadError(f"音源が見つかりません：ID={track_id}")
        st = audio.stat()
        return TrackInput(
            id=str(content.ID),
            title=str(content.Title or ""),
            artist=str(content.ArtistName or ""),
            path=path,
            file_type=int(content.FileType or 0),
            beats=beats,
            phrases=phrases,
            mood=mood,
            fingerprint=fingerprint(path, st.st_size, st.st_mtime_ns, beats),
        )

    def existing_cues(self, track_id: str) -> ExistingCues:
        """既存のキュー。`evaluate` と `writer` だけが使う（`estimate` には渡さない）。"""
        rows = self._db.get_cue(ContentID=track_id).all()
        cues = tuple(
            sorted(
                (
                    ExistingCue(
                        cue_type=int(c.Kind or 0),
                        time_ms=int(c.InMsec or 0),
                        is_loop=c.OutMsec is not None and int(c.OutMsec) > 0,
                    )
                    for c in rows
                    if not c.rb_local_deleted
                ),
                key=lambda c: (c.time_ms, c.cue_type),
            )
        )
        return ExistingCues(track_id=track_id, cues=cues)


@contextmanager
def open_library(
    rekordbox_dir: Path, work_dir: Path, *, keep_copy: bool = False
) -> Generator[Library]:
    """master.db のコピーを取って開く。`with` を抜けると閉じて、コピーを消す。"""
    with snapshot(rekordbox_dir, work_dir, integrity_ok, keep=keep_copy) as snap:
        db = _open_db(snap.db_path)
        try:
            yield Library(db, rekordbox_dir, snap)
        finally:
            db.close()
