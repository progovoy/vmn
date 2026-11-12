"""Plan 40 C5: log buffers live in a per-host dir, one per store: the state
dir, or ``$VMN_EXP_CACHE_DIR``, with a local temp fallback when the state dir
is on a network filesystem or unwritable (a buffer takes a write a second)."""
import logging
import os
import tempfile

import pytest
from vmn_exp.storage import host_dirs

IDENTITY = ("s3", None, "bucket", "prefix")


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.delenv("VMN_EXP_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(host_dirs, "filesystem_type", lambda path: "apfs")
    return str(tmp_path / "xdg" / "vmn-exp")


def _fs(monkeypatch, kind):
    monkeypatch.setattr(host_dirs, "filesystem_type", lambda path: kind)


def _in_tmp(path):
    tmp = tempfile.gettempdir()
    return os.path.commonpath([tmp, path]) == tmp


def test_log_buffers_dir_is_per_store_under_the_state_base(state):
    path = host_dirs.log_buffers_dir(IDENTITY, os.environ)
    assert path == os.path.join(state, "log-buffers", host_dirs.store_id(IDENTITY))
    assert host_dirs.log_buffers_dir(("s3", None, "other", ""), os.environ) != path


def test_cache_dir_env_relocates_log_buffers(state, monkeypatch, tmp_path):
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path / "volume"))
    assert host_dirs.log_buffers_dir(IDENTITY, os.environ) == os.path.join(
        str(tmp_path / "volume"), "log-buffers", host_dirs.store_id(IDENTITY))


def test_a_cache_dir_env_on_a_network_filesystem_is_used_as_given(
        state, monkeypatch, tmp_path, caplog):
    _fs(monkeypatch, "nfs")
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path / "volume"))
    caplog.set_level(logging.WARNING)
    assert host_dirs.log_buffers_dir(IDENTITY, os.environ).startswith(str(tmp_path / "volume"))
    assert not caplog.records


def test_a_network_state_dir_falls_back_to_a_local_temp_dir_with_one_warning(
        state, monkeypatch, caplog):
    _fs(monkeypatch, "nfs4")
    caplog.set_level(logging.WARNING)
    first = host_dirs.log_buffers_dir(IDENTITY, os.environ)
    assert host_dirs.log_buffers_dir(IDENTITY, os.environ) == first
    assert _in_tmp(first) and not first.startswith(state)
    warnings = [r.getMessage() for r in caplog.records if state in r.getMessage()]
    assert len(warnings) == 1 and "nfs4" in warnings[0]


def test_an_unwritable_state_dir_falls_back(monkeypatch, tmp_path, caplog):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    monkeypatch.delenv("VMN_EXP_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(blocker))  # no dir can be made under it
    monkeypatch.setattr(host_dirs, "filesystem_type", lambda path: "apfs")
    caplog.set_level(logging.WARNING)
    path = host_dirs.log_buffers_dir(IDENTITY, os.environ)
    assert _in_tmp(path) and not path.startswith(str(blocker))
    assert any("not writable" in r.getMessage() for r in caplog.records)


def test_log_buffers_bases_lists_the_state_dir_and_the_fallback(state):
    bases = host_dirs.log_buffers_bases(os.environ)
    assert os.path.join(state, "log-buffers") in bases
    fallbacks = [b for b in bases if not b.startswith(state)]
    assert len(fallbacks) == 1 and _in_tmp(fallbacks[0])
    assert fallbacks[0].endswith("log-buffers")
