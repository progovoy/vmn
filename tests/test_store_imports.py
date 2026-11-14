"""``version_stamp.store`` is a git-free leaf: importing it loads no git, no
boto3 and none of vmn's git-bound packages (plan 37, R2), and its modules
import only stdlib, yaml, ``version_stamp.core.{utils,constants}`` and itself."""
import ast
import importlib.util
import os
import pathlib
import subprocess
import sys
import sysconfig

import pytest

_STDLIB = os.path.realpath(sysconfig.get_paths()["stdlib"])

STORE_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "packages" / "vmn" / "src" / "version_stamp" / "store"
)
STORE_FILES = sorted(STORE_DIR.glob("*.py"))
FORBIDDEN = (
    "git", "gitdb", "boto3", "botocore",
    "version_stamp.cli", "version_stamp.snapshot", "version_stamp.devversion",
    "version_stamp.stamping", "version_stamp.backends",
)
ALLOWED_PROJECT = ("yaml", "version_stamp.core.utils", "version_stamp.core.constants")

_CHECK = """
import importlib, sys
for name in sys.argv[1:]:
    importlib.import_module(name)
forbidden = {forbidden!r}
print(sorted(m for m in sys.modules
             if any(m == f or m.startswith(f + ".") for f in forbidden)))
"""


def _module_name(path):
    stem = "" if path.stem == "__init__" else f".{path.stem}"
    return f"version_stamp.store{stem}"


def test_the_store_package_has_its_leaf_modules():
    expected = {"__init__", "names", "areas", "uri", "per_process", "code", "s3_errors"}
    assert expected <= {p.stem for p in STORE_FILES}



def test_the_store_package_has_its_s3_modules():
    expected = {"s3_client", "s3_base", "s3_records", "s3_reads", "s3_store"}
    assert expected <= {p.stem for p in STORE_FILES}

def test_importing_the_store_loads_no_git_boto3_or_vcs_packages():
    out = subprocess.run(
        [sys.executable, "-c", _CHECK.format(forbidden=FORBIDDEN),
         *(_module_name(p) for p in STORE_FILES)],
        capture_output=True, text=True, check=True,
        env={"PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert out.stdout.strip() == "[]"


def _imported_modules(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = "." * node.level + (node.module or "")
            yield importlib.util.resolve_name(name, "version_stamp.store") if node.level else name


def _is_stdlib(module):
    """Whether *module*'s top-level package ships with Python."""
    top = module.split(".")[0]
    names = getattr(sys, "stdlib_module_names", None)
    if names is not None:
        return top in names
    # Python < 3.10: by where the module lives.
    if top in sys.builtin_module_names:
        return True
    spec = importlib.util.find_spec(top) if top else None
    origin = spec and spec.origin
    if origin in ("built-in", "frozen"):
        return True
    origin = origin and os.path.realpath(origin)
    return bool(origin) and origin.startswith(_STDLIB) and "site-packages" not in origin


def _allowed(module):
    if _is_stdlib(module) or module in ALLOWED_PROJECT:
        return True
    return module == "version_stamp.store" or module.startswith("version_stamp.store.")


@pytest.mark.parametrize("path", STORE_FILES, ids=lambda p: p.name)
def test_store_modules_import_only_the_allowed_set(path):
    assert [m for m in _imported_modules(path) if not _allowed(m)] == []
