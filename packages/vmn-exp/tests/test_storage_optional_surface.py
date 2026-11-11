"""The optional storage surface is written down and does not grow (plan 41 D12).

Callers find optional storage methods by ``hasattr(x, "name")`` or
``getattr(x, "name", default)``. Every such probe in the two vmn_exp src roots
is counted and compared with storage_optional_probes.py: a new name or a
higher count fails, and so does a stale entry, so the table only shrinks.
"""
import ast
from collections import Counter
from pathlib import Path

from exp_helpers import _PROJECT_ROOT
from storage_optional_probes import OTHER_PROBES, STORAGE_PROBES

SRC_ROOTS = [Path(_PROJECT_ROOT) / "packages" / dist / "src" / "vmn_exp"
             for dist in ("vmn-exp-sdk", "vmn-exp")]


def probes(source):
    """``Counter({name: count})`` of the attribute names *source* probes."""
    found = Counter()
    for node in ast.walk(ast.parse(source)):
        name = _probed_name(node)
        if name is not None:
            found[name] += 1
    return found


def _probed_name(node):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    arity = {"hasattr": 2, "getattr": 3}.get(node.func.id)
    if arity is None or len(node.args) != arity or node.keywords:
        return None
    name = node.args[1]
    return name.value if isinstance(name, ast.Constant) and isinstance(name.value, str) else None


def _actual_probes():
    found = Counter()
    for root in SRC_ROOTS:
        for path in sorted(root.rglob("*.py")):
            found += probes(path.read_text(encoding="utf-8"))
    return found


def _known_probes():
    assert not set(STORAGE_PROBES) & set(OTHER_PROBES), "a name is either storage or other"
    return {**STORAGE_PROBES, **OTHER_PROBES}


def test_probe_scanner_finds_hasattr_and_three_argument_getattr():
    source = (
        "def f(storage, name):\n"
        "    if hasattr(storage, 'is_remote') and hasattr(storage, 'is_remote'):\n"
        "        pass\n"
        "    getattr(storage, 'direct_files', None)\n"
        "    getattr(storage, 'save')\n"
        "    getattr(storage, name, None)\n"
        "    storage.hasattr(storage, 'x')\n"
    )
    assert probes(source) == Counter({"is_remote": 2, "direct_files": 1})


def test_no_new_optional_storage_probes():
    known = _known_probes()
    grown = {name: count for name, count in _actual_probes().items()
             if count > known.get(name, 0)}
    assert not grown, (
        "new hasattr/getattr probes; add each to storage_optional_probes.py "
        "(STORAGE_PROBES plus an experiments.md row if the receiver is a storage, "
        f"else OTHER_PROBES), or call a method SnapshotStorage defines: {grown}"
    )


def test_probe_table_has_no_stale_entries():
    actual = _actual_probes()
    stale = {name: f"{count} -> {actual.get(name, 0)}"
             for name, count in _known_probes().items() if actual.get(name, 0) < count}
    assert not stale, f"lower (or drop) these in storage_optional_probes.py: {stale}"

