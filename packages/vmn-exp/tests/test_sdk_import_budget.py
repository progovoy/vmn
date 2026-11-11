"""What ``import vmn_exp.sdk`` costs a job that only logs metrics (plan 41 D1).

The closure is static: the vmn_exp modules reached from ``vmn_exp.sdk`` by
imports that run at import time — module top level, including ``if``/``try``/
``with`` blocks there, but not ``if TYPE_CHECKING:`` and not imports inside a
function or class body. Importing ``a.b.c`` also counts the packages ``a`` and
``a.b``.

The FORBIDDEN prefixes are the hard gate. BUDGET may be lowered freely; it may
be raised only in a commit whose message names the module it adds.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

from exp_helpers import SRC_DIRS

SRC_ROOTS = [Path(src) for src in SRC_DIRS]
FORBIDDEN = (
    "vmn_exp.core.index",
    "vmn_exp.core.similar",
    "vmn_exp.core.sqlite",
    "vmn_exp.core.journal_reader",
)
BUDGET = 159


def _path_of(module):
    rel = Path(*module.split("."))
    for root in SRC_ROOTS:
        for candidate in (root / rel / "__init__.py", root.joinpath(*rel.parts[:-1], rel.name + ".py")):
            if candidate.exists():
                return candidate
    return None


def _is_type_checking(node):
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _import_time_nodes(body):
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if not _is_type_checking(node):
                yield from _import_time_nodes(node.body)
            yield from _import_time_nodes(node.orelse)
        elif isinstance(node, ast.With):
            yield from _import_time_nodes(node.body)
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *(h.body for h in node.handlers)):
                yield from _import_time_nodes(block)


def _base_of(module, path, node):
    if not node.level:
        return node.module or ""
    parts = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    parts = parts[: len(parts) - node.level + 1]
    return ".".join(parts + ([node.module] if node.module else []))


def _imported(module, path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in _import_time_nodes(tree.body):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
            continue
        base = _base_of(module, path, node)
        yield base
        yield from (f"{base}.{a.name}" for a in node.names if _path_of(f"{base}.{a.name}"))


def _with_parents(module):
    parts = module.split(".")
    return [".".join(parts[:n]) for n in range(1, len(parts) + 1)]


def sdk_closure():
    seen, todo = set(), ["vmn_exp.sdk"]
    while todo:
        module = todo.pop()
        for name in _with_parents(module):
            path = _path_of(name)
            if name in seen or not name.startswith("vmn_exp") or path is None:
                continue
            seen.add(name)
            todo.extend(_imported(name, path))
    return seen


def _forbidden(closure):
    return sorted(m for m in closure if any(m == p or m.startswith(p) for p in FORBIDDEN))


def test_sdk_import_closure_has_no_index_modules():
    assert _forbidden(sdk_closure()) == []


def test_sdk_import_closure_within_budget():
    closure = sdk_closure()
    assert len(closure) <= BUDGET, f"{len(closure)} modules > BUDGET {BUDGET}"


def _run(script):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(SRC_DIRS)}
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


_EXACT_PARENT = """\
import sys
from vmn_exp.core.refs import resolve_parent

class Storage:
    def exists(self, app_name, verstr):
        return True

print(resolve_parent(Storage(), "app", explicit="0.0.1-dev.abc.r1"))
print("vmn_exp.core.index" in sys.modules)
"""


def test_exact_parent_ref_resolves_without_importing_index():
    assert _run(_EXACT_PARENT).splitlines() == ["('0.0.1-dev.abc.r1', None)", "False"]


def test_relisted_still_importable_from_index_metric_reads():
    from vmn_exp.core import index_metric_reads, metric_object_reads

    for name in ("MetricObjectGone", "object_read", "relisted"):
        assert getattr(index_metric_reads, name) is getattr(metric_object_reads, name)
