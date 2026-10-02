"""Per-host state (index cache, push ledger) lives outside the store (plan 14 §1.4)."""
import os
import sys

import pytest

from vmn_exp.core.push_ledger import PushLedger
from vmn_exp.storage import host_dirs
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"


def _files_under(path):
    return [os.path.join(d, f) for d, _, fs in os.walk(path) for f in fs]


@pytest.fixture
def override(monkeypatch, tmp_path):
    monkeypatch.delenv("VMN_INDEX_CACHE_DIR", raising=False)
    base = tmp_path / "hoststate"
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(base))
    return base


def _local(tmp_path, name):
    st = LocalSnapshotStorage(str(tmp_path / name))
    st.save(APP, "1.0.0-dev.a", {"verstr": "1.0.0-dev.a"}, {})
    return st


def test_index_cache_lands_in_the_override_dir(override, tmp_path):
    st = _local(tmp_path, "store")
    path = st.index_cache_path(APP)
    assert path.startswith(str(override / "index") + os.sep)
    assert path.endswith(".sqlite")


def test_two_file_roots_get_different_cache_files(override, tmp_path):
    a = _local(tmp_path, "a").index_cache_path(APP)
    b = _local(tmp_path, "b").index_cache_path(APP)
    assert a != b
    assert _local(tmp_path, "a").index_cache_path(APP) == a


def test_index_cache_disabled_by_legacy_none(monkeypatch, tmp_path):
    monkeypatch.setenv("VMN_INDEX_CACHE_DIR", "none")
    assert _local(tmp_path, "store").index_cache_path(APP) is None


def test_push_ledger_lives_in_the_state_dir(override, tmp_path):
    st = _local(tmp_path, "store")
    ledger = PushLedger(st, APP, "rid")
    ledger.put("1.0.0-dev.a", {"complete": True})
    assert ledger.dir.startswith(str(override / "push") + os.sep)
    assert "rid" in ledger.dir
    assert ledger.get("1.0.0-dev.a") == {"complete": True}


def test_nothing_but_records_written_into_the_store(override, tmp_path):
    from vmn_exp.core.index import ExperimentIndex

    st = _local(tmp_path, "store")
    ExperimentIndex(st, APP, st.index_cache_path(APP)).refresh()
    PushLedger(st, APP, "rid").put("1.0.0-dev.a", {"complete": True})
    stray = [p for p in _files_under(tmp_path / "store")
             if ".sqlite" in p or f"{os.sep}.push{os.sep}" in p]
    assert stray == []
    assert any(p.endswith(".sqlite") for p in _files_under(override))


def test_platform_defaults(monkeypatch):
    for var in ("VMN_EXP_CACHE_DIR", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        assert host_dirs.cache_base() == os.path.join(home, "Library", "Caches", "vmn-exp")
        assert host_dirs.state_base() == os.path.join(
            home, "Library", "Application Support", "vmn-exp")
    else:
        assert host_dirs.cache_base() == os.path.join(home, ".cache", "vmn-exp")
        assert host_dirs.state_base() == os.path.join(home, ".local", "state", "vmn-exp")


def test_xdg_vars_win_over_platform_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("VMN_EXP_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    assert host_dirs.cache_base() == str(tmp_path / "c" / "vmn-exp")
    assert host_dirs.state_base() == str(tmp_path / "s" / "vmn-exp")


def test_app_names_that_slug_alike_get_distinct_paths(tmp_path, monkeypatch):
    from vmn_exp.storage import host_dirs

    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("VMN_INDEX_CACHE_DIR", raising=False)
    ident = ("file", str(tmp_path / "store"))
    assert host_dirs.index_cache_path(ident, "a.b") != host_dirs.index_cache_path(
        ident, "a_b"
    )
    assert host_dirs.push_ledger_dir(ident, "r", "a.b") != host_dirs.push_ledger_dir(
        ident, "r", "a_b"
    )
