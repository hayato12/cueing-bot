"""コマンドラインの入り口。コマンドはスプリントで足していく（architecture.md 2 章の cli）。"""

from __future__ import annotations

import argparse

from cueing_bot import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cueing-bot", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
