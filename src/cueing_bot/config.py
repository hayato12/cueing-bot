"""場所の既定値。環境変数で変えられる。"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """個人データの置き場（リポジトリの外。architecture.md 4 章）。"""
    env = os.environ.get("CUEING_BOT_DATA_DIR")
    return Path(env).expanduser() if env else Path.home() / "llm" / "cueing-bot" / "data"


def rekordbox_dir() -> Path:
    """Rekordbox の master.db があるフォルダ。解析ファイルはこの下の `share/` にある。"""
    env = os.environ.get("CUEING_BOT_REKORDBOX_DIR")
    return Path(env).expanduser() if env else Path.home() / "Library" / "Pioneer" / "rekordbox"
