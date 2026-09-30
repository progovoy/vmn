"""vmn_exp._base: the helpers the job SDK copies from version_stamp.core so it
does not depend on vmn. The copies must behave exactly like the originals."""
import logging
import os

import pytest

from version_stamp.core import utils as vmn_utils
from vmn_exp import _base

NAMES = ["0.0.1-dev.abc.r1", "", ".", "..", "a/b", "a\\b", "a\0b", "ok_name", "x..y"]
APPS = ["app", "root/svc", "", "/abs", "root//svc", "root/../x", "a/./b"]
RAWS = [None, "", "verstr: v1\n", "a: 1\n", "- 1\n", "{bad", "verstr: v1\nnote: n\n"]


@pytest.mark.parametrize("name", NAMES)
def test_valid_path_component_matches_vmn(name):
    assert _base.valid_path_component(name) == vmn_utils.valid_path_component(name)


@pytest.mark.parametrize("app", APPS)
def test_valid_app_path_matches_vmn(app):
    assert _base.valid_app_path(app) == vmn_utils.valid_app_path(app)


@pytest.mark.parametrize("raw", RAWS)
def test_parse_record_metadata_matches_vmn(raw):
    assert _base.parse_record_metadata(raw) == vmn_utils.parse_record_metadata(raw)


def test_yaml_safe_load_matches_vmn():
    text = "a: [1, 2]\nb: {c: x}\n"
    assert _base.yaml_safe_load(text) == vmn_utils.yaml_safe_load(text)


def test_now_iso_is_utc_with_z_suffix():
    stamp = _base.now_iso()
    assert stamp.endswith("Z") and "+00:00" not in stamp


def test_sha256_file_matches_vmn(tmp_path):
    path = tmp_path / "blob"
    path.write_bytes(os.urandom(200_000))
    assert _base.sha256_file(str(path)) == vmn_utils.sha256_file(str(path))


@pytest.mark.parametrize("marker", [".git", ".vmn"])
def test_resolve_root_path_matches_vmn(tmp_path, monkeypatch, marker):
    (tmp_path / marker).mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    monkeypatch.setenv("VMN_WORKING_DIR", str(deep))
    assert _base.resolve_root_path() == vmn_utils.resolve_root_path()


def test_logger_is_the_one_the_vmn_cli_configures():
    assert _base.VMN_LOGGER is logging.getLogger("vmn")
    assert _base.ensure_logger() is _base.VMN_LOGGER


@pytest.mark.parametrize("override", [None, "custom.lock"])
def test_repo_lock_path_matches_vmn(tmp_path, monkeypatch, override):
    from version_stamp.core.repo_lock import get_repo_lock

    if override:
        monkeypatch.setenv("VMN_LOCK_FILE_PATH", str(tmp_path / override))
    else:
        monkeypatch.delenv("VMN_LOCK_FILE_PATH", raising=False)
    root = str(tmp_path)
    assert _base.get_repo_lock(root).lock_file == get_repo_lock(root).lock_file
