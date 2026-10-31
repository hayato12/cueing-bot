"""`estimate`・`evaluate` が `model` と標準ライブラリ以外に依存していないか（architecture.md 2 章）。"""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "cueing_bot"
PURE_PACKAGES = ("evaluate", "estimate")
ALLOWED_INTERNAL = ("cueing_bot.model", "cueing_bot.evaluate", "cueing_bot.estimate")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_pure_packages_depend_only_on_model_and_stdlib() -> None:
    files = [p for pkg in PURE_PACKAGES for p in (SRC / pkg).rglob("*.py")]
    assert files
    bad: list[str] = []
    for f in files:
        for name in imported_modules(f):
            top = name.split(".")[0]
            if top == "cueing_bot":
                if not name.startswith(ALLOWED_INTERNAL):
                    bad.append(f"{f.name}: {name}")
            elif top not in sys.stdlib_module_names and top != "__future__":
                bad.append(f"{f.name}: {name}")
    assert bad == []
