"""コマンドラインの入り口。コマンドはスプリントで足していく（architecture.md 2 章の cli）。"""

from __future__ import annotations

import argparse
from pathlib import Path

from cueing_bot import __version__, config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cueing-bot", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    lib = sub.add_parser("library", help="Rekordbox のライブラリを読む（master.db のコピーを使う）")
    lib.add_argument(
        "--rekordbox-dir",
        type=Path,
        default=None,
        help="master.db のあるフォルダ（既定は ~/Library/Pioneer/rekordbox）",
    )
    lib_sub = lib.add_subparsers(dest="library_command")
    lib_sub.add_parser("playlists", help="プレイリストの一覧を出す")
    inspect = lib_sub.add_parser(
        "inspect", help="プレイリストの曲を読み、グリッド・フレーズ・既存のキューの数を出す"
    )
    inspect.add_argument("playlist", help="プレイリストの名前")
    return parser


def _cmd_library(args: argparse.Namespace) -> int:
    # pyrekordbox（と暗号化 DB を開く仕組み）は重いので、使うときだけ読み込む
    from cueing_bot.library.reader import PlaylistError, TrackReadError, open_library

    if args.library_command not in ("playlists", "inspect"):
        print("library のサブコマンド（playlists・inspect）を指定してください")
        return 2
    rb_dir: Path = args.rekordbox_dir or config.rekordbox_dir()
    work = config.data_dir() / "tmp"
    with open_library(rb_dir, work) as lib:
        snap = lib.snapshot
        print(f"master.db のコピー：{snap.seconds:.1f} 秒（{snap.attempts} 回目で取得）")
        if args.library_command == "playlists":
            for pl in lib.playlists():
                print(f"{'[folder] ' if pl.is_folder else ''}{pl.name}")
            return 0
        if args.library_command == "inspect":
            try:
                ids = lib.track_ids_in_playlist(args.playlist)
            except PlaylistError as e:
                print(e)
                return 2
            failed: list[str] = []
            print("曲\t拍\tフレーズ\tmood\t既存のキュー")
            for track_id in ids:
                try:
                    t = lib.track_input(track_id)
                except TrackReadError as e:
                    failed.append(str(e))
                    continue
                n_cues = len(lib.existing_cues(track_id).cues)
                print(f"{t.title}\t{len(t.beats)}\t{len(t.phrases)}\t{t.mood}\t{n_cues}")
            print(f"\n{len(ids) - len(failed)} / {len(ids)} 曲を読めました")
            for msg in failed:
                print(f"  失敗：{msg}")
            return 0 if not failed else 1
    return 2  # ここには来ない


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "library":
        return _cmd_library(args)
    # コマンドを指定しなかったときは使い方を出し、失敗（2）で終える。
    # スクリプトや MCP から呼んだときに、何もせず成功したように見せないため
    parser.print_usage()
    return 2
