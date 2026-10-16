"""Plan 25 F3: SQLite's locks are unreliable on network filesystems, so a
cache dir there falls back to a local temp dir (once warned), unless the
user picked it explicitly."""
import logging
import os
import sys
import tempfile

import pytest
from vmn_exp.storage import fs_type, host_dirs


@pytest.fixture
def xdg(monkeypatch, tmp_path):
    for var in ("VMN_INDEX_CACHE_DIR", "VMN_EXP_CACHE_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    return str(tmp_path / "xdg" / "vmn-exp")


def _fs(kind):
    return lambda path: kind


def test_a_local_cache_dir_is_kept(xdg, monkeypatch):
    monkeypatch.setattr(host_dirs, "filesystem_type", _fs("apfs"))
    assert host_dirs.cache_base() == xdg


@pytest.mark.parametrize("kind", ["nfs", "nfs4", "cifs", "smbfs", "fuse.sshfs"])
def test_a_network_cache_dir_falls_back_to_tmp(xdg, monkeypatch, kind):
    monkeypatch.setattr(host_dirs, "filesystem_type", _fs(kind))
    base = host_dirs.cache_base()
    assert base != xdg
    assert os.path.commonpath([tempfile.gettempdir(), base]) == tempfile.gettempdir()
    assert host_dirs.index_cache_root() == base


def test_the_fallback_is_warned_about_once(xdg, monkeypatch, caplog):
    monkeypatch.setattr(host_dirs, "filesystem_type", _fs("nfs"))
    caplog.set_level(logging.WARNING)
    host_dirs.cache_base()
    host_dirs.cache_base()
    warnings = [r for r in caplog.records if xdg in r.getMessage()]
    assert len(warnings) == 1 and "nfs" in warnings[0].getMessage()


def test_an_explicit_cache_dir_is_kept_even_on_nfs(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(host_dirs, "filesystem_type", _fs("nfs"))
    monkeypatch.setenv("VMN_EXP_CACHE_DIR", str(tmp_path / "chosen"))
    caplog.set_level(logging.WARNING)
    assert host_dirs.cache_base() == str(tmp_path / "chosen")
    assert not caplog.records


def test_the_state_dir_is_not_redirected(xdg, monkeypatch, tmp_path):
    monkeypatch.setattr(host_dirs, "filesystem_type", _fs("nfs"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert host_dirs.state_base() == str(tmp_path / "state" / "vmn-exp")


def test_the_type_of_a_path_not_created_yet_is_its_parents(tmp_path):
    assert fs_type.filesystem_type(str(tmp_path / "a" / "b")) == \
        fs_type.filesystem_type(str(tmp_path))


@pytest.mark.skipif(sys.platform not in ("darwin", "linux"), reason="posix only")
def test_the_real_detection_sees_a_local_temp_dir(tmp_path):
    kind = fs_type.filesystem_type(str(tmp_path))
    assert kind and not fs_type.is_network_fs(kind)


def test_linux_mounts_pick_the_longest_mount_point():
    mounts = (
        "/dev/sda1 / ext4 rw 0 0\n"
        "server:/export /home nfs4 rw 0 0\n"
        "tmpfs /home/u/tmp tmpfs rw 0 0\n"
    )
    assert fs_type.fs_type_from_mounts(mounts, "/home/u/.cache") == "nfs4"
    assert fs_type.fs_type_from_mounts(mounts, "/home/u/tmp/x") == "tmpfs"
    assert fs_type.fs_type_from_mounts(mounts, "/var/x") == "ext4"
    assert fs_type.fs_type_from_mounts(mounts, "/homework") == "ext4"
