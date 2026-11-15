"""``version_stamp.snapshot`` and ``version_stamp.store`` sit below the CLI:
no module of theirs imports ``version_stamp.cli``, not even lazily."""
import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "packages" / "vmn" / "src"


def _imported(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            yield from (f"{node.module}.{alias.name}" for alias in node.names)


def _cli_imports(package):
    for path in sorted((SRC / "version_stamp" / package).rglob("*.py")):
        for name in _imported(ast.parse(path.read_text())):
            if name == "version_stamp.cli" or name.startswith("version_stamp.cli."):
                yield f"{path.relative_to(SRC)}: {name}"


@pytest.mark.parametrize("package", ["snapshot", "store"])
def test_package_never_imports_the_cli(package):
    assert list(_cli_imports(package)) == []
