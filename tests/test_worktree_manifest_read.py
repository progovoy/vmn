"""worktree_state.read_manifest and its use by `vmn wt list/remove`."""
import json
from types import SimpleNamespace

import pytest

from version_stamp.cli import worktrees
from version_stamp.cli.worktree_state import ISLAND_MANIFEST_FILENAME, read_manifest
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def _ctx(root, name=None):
    return SimpleNamespace(
        args=SimpleNamespace(name=name, base_path="islands"),
        vcs=SimpleNamespace(vmn_root_path=str(root)),
    )


def _island(root, name, text):
    island = root / "islands" / name
    island.mkdir(parents=True)
    (island / ISLAND_MANIFEST_FILENAME).write_text(text)
    return island


def test_read_manifest_parses_a_manifest(tmp_path):
    path = tmp_path / ISLAND_MANIFEST_FILENAME
    path.write_text(json.dumps({"name": "a"}))
    assert read_manifest(str(path)) == {"name": "a"}


def test_read_manifest_is_none_for_corrupt_or_missing(tmp_path):
    path = tmp_path / ISLAND_MANIFEST_FILENAME
    assert read_manifest(str(path)) is None
    path.write_text("{not json")
    assert read_manifest(str(path)) is None


def test_list_skips_a_corrupt_manifest(tmp_path, capsys, caplog):
    _island(tmp_path, "bad", "{not json")
    _island(tmp_path, "good", json.dumps({"name": "good", "source": {}}))
    assert worktrees.worktree_list(_ctx(tmp_path)) == 0
    assert "good" in capsys.readouterr().out
    assert "Skipping corrupt manifest" in caplog.text


def test_remove_refuses_a_corrupt_manifest_and_keeps_the_island(tmp_path, caplog):
    island = _island(tmp_path, "bad", "{not json")
    assert worktrees.worktree_remove(_ctx(tmp_path, "bad")) == 1
    assert island.is_dir()
    assert "corrupt" in caplog.text.lower()
