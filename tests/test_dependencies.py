"""`estimate`・`evaluate` が `model` と標準ライブラリ以外に依存していないか（architecture.md 2 章）。"""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "cueing_bot"
ALLOWED = {
    "evaluate": ("cueing_bot.model", "cueing_bot.evaluate"),
    "estimate": ("cueing_bot.model", "cueing_bot.estimate"),
}


def imported_modules(path: Path) -> set[str]:
    """ファイルが読み込むモジュールの名前。相対の import（`from ..x import y`）は絶対の名前に直す。"""
    # ファイルのあるパッケージ（`__init__.py` でも普通のファイルでも、最後の 1 つを落とせばよい）
    module_parts = ["cueing_bot", *path.relative_to(SRC).with_suffix("").parts][:-1]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                names.add(node.module or "")
            else:
                base = module_parts[: len(module_parts) - (node.level - 1)]
                names.add(".".join([*base, *([node.module] if node.module else [])]))
    return names


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_pure_packages_depend_only_on_model_and_stdlib(package: str) -> None:
    files = list((SRC / package).rglob("*.py"))
    if package == "evaluate":
        assert files
    bad: list[str] = []
    for f in files:
        for name in imported_modules(f):
            top = name.split(".")[0]
            if top == "cueing_bot":
                if not any(name == a or name.startswith(a + ".") for a in ALLOWED[package]):
                    bad.append(f"{f.name}: {name}")
            elif top not in sys.stdlib_module_names and top != "__future__":
                bad.append(f"{f.name}: {name}")
    assert bad == []
