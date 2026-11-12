"""core/index.py is a facade over mixin modules (plan 44 G17): the names
importers use and tests patch stay on ``vmn_exp.core.index``, and a patch
there still reaches the code that reads it, wherever that code lives."""
import ast
import logging
import symtable
from pathlib import Path

import pytest

from fakes.clock import FakeClock
from similar_seed import seed, verstr
from vmn_exp.core import index as index_module
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
LOGGER = "vmn_exp.core.index"
TESTS = Path(__file__).resolve().parents[1]
INDEX_PY = Path(index_module.__file__)
MODULE = "vmn_exp.core.index"
# Patched by tests, read by no function of core/index.py: its callers reach
# it as a module attribute from other modules (ui/index.py, ui/experiment_source.py).
NOT_READ_INSIDE = {"direct_rows"}
PUBLIC_SURFACE = [
    "adopt", "check_vmx", "close", "drift", "follower", "freshness", "full_listing_due",
    "full_sweep_sec", "hint", "journal_at", "journaled", "last_reconcile_at", "overflowed",
    "path", "published", "reconcile", "record_count", "records", "refresh", "refresh_if_stale",
    "refreshing", "resume_journal", "rows", "run_states", "snapshot", "snapshot_now", "sync",
    "use_io_process", "wait_revalidated",
]


class RemoteStorage(LocalSnapshotStorage):
    """A local store the index treats as remote (chunked, rows-first loads)."""

    def is_remote(self):
        return True


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _index(storage, tmp_path, clock=None, name="idx.sqlite"):
    return ExperimentIndex(storage, APP, str(tmp_path / name), clock=clock or FakeClock())


def _verstrs(snapshot):
    return [row["verstr"] for row in snapshot.rows]


# -- the module's names ------------------------------------------------------

def test_core_index_still_exposes_the_names_importers_use():
    for name in ("ExperimentIndex", "shared_index", "indexed_snapshot", "indexed_status_rows",
                 "direct_rows", "direct_snapshot", "snapshot_of_folds", "IOProcessError",
                 "FIRST_ROWS", "FIRST_ROWS_MAX", "_REMOTE_CHUNK", "_REMOTE_WORKERS",
                 "RETRY_UNREADABLE_SEC", "refresh_record", "update_record", "kept_parts",
                 "first_rows", "_SHARED", "IndexSnapshot", "DEFAULT_FULL_SWEEP_SEC"):
        assert hasattr(index_module, name), name


def _module_aliases(tree):
    aliases = {MODULE}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(a.asname for a in node.names if a.name == MODULE and a.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "vmn_exp.core":
            aliases.update(a.asname or a.name for a in node.names if a.name == "index")
    return aliases


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _patched_in(tree):
    aliases, found = _module_aliases(tree), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            if func in ("setattr", "patch") and first.value.startswith(MODULE + "."):
                rest = first.value[len(MODULE) + 1:]
                if "." not in rest:
                    found.add(rest)
        elif func in ("setattr", "object") and _dotted(first) in aliases and len(node.args) > 1:
            name = node.args[1]
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                found.add(name.value)
    return found


def patched_names():
    """Every name a test sets on ``vmn_exp.core.index``."""
    names = set()
    for path in TESTS.rglob("*.py"):
        names |= _patched_in(ast.parse(path.read_text(), str(path)))
    return names


def _global_loads(path):
    """``{scope kind: names}`` loaded as globals in *path*: ``module`` for
    the top level, ``function`` for any function body (methods included)."""
    loads = {"module": set(), "function": set()}

    def walk(table):
        for sym in table.get_symbols():
            if not sym.is_referenced():
                continue
            if table.get_type() == "module":
                loads["module"].add(sym.get_name())
            elif sym.is_global():
                loads["function" if table.get_type() == "function" else "module"].add(sym.get_name())
        for child in table.get_children():
            walk(child)

    walk(symtable.symtable(path.read_text(), str(path), "exec"))
    return loads


# The modules core/index.py's mixins and moved functions live in (plan 44 G17).
FACADE_PARTS = ("index_surface", "index_refresh", "index_load", "index_publish",
                "index_persist", "index_read", "index_direct")


def _facade_parts():
    """The parts core/index.py is split into: its mixins' modules and the
    planned part modules that exist."""
    modules = {cls.__module__ for cls in ExperimentIndex.__mro__[1:-1]}
    modules |= {f"vmn_exp.core.{name}" for name in FACADE_PARTS
                if INDEX_PY.with_name(name + ".py").exists()}
    return {m: INDEX_PY.with_name(m.rsplit(".", 1)[1] + ".py") for m in modules - {MODULE}}


def test_every_name_tests_patch_on_core_index_is_read_inside_core_index():
    patched = patched_names()
    assert {"_REMOTE_CHUNK", "RETRY_UNREADABLE_SEC", "refresh_record", "_SHARED"} <= patched
    unbound = sorted(n for n in patched if n not in vars(index_module))
    assert not unbound, f"patched on core.index but not bound there: {unbound}"
    for module, path in _facade_parts().items():
        loads = _global_loads(path)
        moved = sorted(patched & (loads["module"] | loads["function"]))
        assert not moved, f"{module} reads {moved}: a patch on core.index would miss it"
    inside = _global_loads(INDEX_PY)["function"]
    unread = sorted(patched - inside - NOT_READ_INSIDE)
    assert not unread, f"no function of core/index.py reads {unread}: patches would miss"


def test_experiment_index_public_surface_is_unchanged():
    assert sorted(n for n in dir(ExperimentIndex) if not n.startswith("_")) == PUBLIC_SURFACE


def test_no_index_method_is_defined_by_two_bases():
    owners = {}
    for cls in ExperimentIndex.__mro__[:-1]:
        for name in vars(cls):
            if not (name.startswith("__") and name.endswith("__")):
                owners.setdefault(name, []).append(cls.__name__)
    twice = {name: classes for name, classes in owners.items() if len(classes) > 1}
    assert not twice


# -- the logger --------------------------------------------------------------

class FailingVmx:
    def state(self):
        return {"total": 1, "done": 0}

    def list_all(self):
        pass

    def step(self, *args):
        raise RuntimeError("throttled")


def test_index_warnings_are_logged_as_vmn_exp_core_index(storage, tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    index = _index(storage, tmp_path)
    index._vmx = FailingVmx()
    assert index.check_vmx() == 0

    index.refresh = lambda: (_ for _ in ()).throw(RuntimeError("store gone"))
    index._revalidate_in_background()
    index.wait_revalidated(10)

    logged = [(r.name, r.levelno) for r in caplog.records]
    assert (LOGGER, logging.WARNING) in logged
    assert (LOGGER, logging.DEBUG) in logged


# -- patches on core.index reach the moved code ------------------------------

def test_patching_remote_chunk_on_core_index_changes_the_load_chunk_size(tmp_path, monkeypatch):
    storage = RemoteStorage(str(tmp_path / "store"), area="runs")
    for n in range(1, 6):
        seed(storage, APP, verstr(n))
    monkeypatch.setattr(index_module, "_REMOTE_CHUNK", 2)
    index, parts = _index(storage, tmp_path), []
    real = index._refresh_part
    index._refresh_part = lambda work, *rest: parts.append(len(work)) or real(work, *rest)

    assert len(index.refresh().snapshot().rows) == 5
    assert parts[0] == 2


def test_patching_retry_unreadable_sec_on_core_index_changes_when_a_failed_record_is_reread(
        storage, tmp_path, monkeypatch):
    clock, broken = FakeClock(), {seed(storage, APP, verstr(1))}
    real = index_module.refresh_record

    def refresh_record(key, *args, **kwargs):
        if key in broken:
            raise ValueError("unreadable")
        return real(key, *args, **kwargs)

    monkeypatch.setattr(index_module, "refresh_record", refresh_record)
    monkeypatch.setattr(index_module, "RETRY_UNREADABLE_SEC", 5)
    index = _index(storage, tmp_path, clock).refresh()
    broken.clear()

    clock.advance(4)
    assert index.refresh().freshness()["unreadable"]["count"] == 1
    clock.advance(1)
    assert "unreadable" not in index.refresh().freshness()


def test_patching_refresh_record_on_core_index_reaches_a_refresh(storage, tmp_path, monkeypatch):
    v, seen, real = seed(storage, APP, verstr(1)), [], index_module.refresh_record
    monkeypatch.setattr(index_module, "refresh_record",
                        lambda key, *a: seen.append(key) or real(key, *a))

    assert _verstrs(_index(storage, tmp_path).refresh().snapshot()) == [v]
    assert seen == [v]


def test_patching_update_record_on_core_index_reaches_a_refresh(storage, tmp_path, monkeypatch):
    v, seen, real = seed(storage, APP, verstr(1)), [], index_module.update_record
    monkeypatch.setattr(index_module, "update_record",
                        lambda st, d, app, key, *a: seen.append(key) or real(st, d, app, key, *a))

    _index(storage, tmp_path).refresh()
    assert seen == [v]


def test_patching_first_rows_on_core_index_bounds_what_snapshot_now_serves(tmp_path, monkeypatch):
    storage = RemoteStorage(str(tmp_path / "store"), area="runs")
    for n in range(1, 7):
        seed(storage, APP, verstr(n), ts=f"2026-01-01T00:00:0{n}Z")
    _index(storage, tmp_path).refresh()
    monkeypatch.setattr(index_module, "FIRST_ROWS", 2)
    monkeypatch.setattr(index_module, "FIRST_ROWS_MAX", 2)
    index, served = _index(storage, tmp_path), []
    real = index._load_records
    index._load_records = lambda: served.append(index.snapshot_now(wait_sec=0)) or real()

    index.refresh()
    index.wait_revalidated(10)
    assert _verstrs(served[0]) == [verstr(5), verstr(6)]
    assert served[0].loading == (2, 6)


# -- the process-wide registry -----------------------------------------------

def test_shared_index_registry_is_one_object_per_process(storage, tmp_path, monkeypatch):
    monkeypatch.setattr(index_module, "_SHARED", {})
    cache, clock = str(tmp_path / "idx.sqlite"), FakeClock()

    first = index_module.shared_index(storage, APP, cache, clock=clock)
    assert index_module.shared_index(storage, APP, cache, clock=clock) is first


def test_patching_the_registry_through_core_index_isolates_a_test(storage, tmp_path, monkeypatch):
    cache, clock = str(tmp_path / "idx.sqlite"), FakeClock()
    monkeypatch.setattr(index_module, "_SHARED", {})
    first = index_module.shared_index(storage, APP, cache, clock=clock)

    monkeypatch.setattr(index_module, "_SHARED", {})
    assert index_module.shared_index(storage, APP, cache, clock=clock) is not first


def test_patching_shared_index_on_core_index_reaches_indexed_snapshot(storage, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("no index")

    monkeypatch.setattr(index_module, "shared_index", broken)
    answer = index_module.indexed_snapshot(storage, APP, fallback=lambda *a: "direct",
                                           clock=FakeClock())
    assert answer == "direct"


# -- state shared between indexes --------------------------------------------

def test_adopt_serves_the_other_indexes_records_and_keeps_its_own_hints(storage, tmp_path):
    first = seed(storage, APP, verstr(1))
    other = _index(storage, tmp_path, name="other.sqlite")
    other.journaled = True
    other.reconcile()
    other.refresh()
    second = seed(storage, APP, verstr(2))
    assert _verstrs(other.refresh().snapshot()) == [first]  # journaled: unhinted, unseen
    index = _index(storage, tmp_path)
    index.hint(second)

    index.adopt(other)
    assert _verstrs(index.snapshot()) == [first]
    assert _verstrs(index.refresh().snapshot()) == [first, second]


def test_a_lean_copy_shares_the_store_and_builds_no_snapshot(storage, tmp_path):
    v = seed(storage, APP, verstr(1))
    index = _index(storage, tmp_path)

    assert index.sync() is True
    assert index.published is None
    assert index._lean_index._store is index._store
    assert _verstrs(_index(storage, tmp_path).refresh().snapshot()) == [v]
