"""``vmn-exp ui cache resync|rebuild [--workspace] [--config]`` (plan 11 §4.6):
calls a running server's API, or works on the cache files directly."""
import os
from urllib.error import URLError

import pytest

from version_stamp.core.logging import init_stamp_logger
from vmn_exp.ui import cache_cli


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


def _args(tmp_path, *argv):
    from version_stamp.cli.args import parse_user_commands

    return parse_user_commands(["ui", *argv, "--data-dir", str(tmp_path / "ui")])


@pytest.fixture
def manager(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui"))
    manager.add_store("ws", f"file://{tmp_path}/store")
    manager.add_store("other", f"file://{tmp_path}/other")
    return manager


def _cache_file(tmp_path, manager, name):
    from vmn_exp.ui.index import s3_cache_path

    path = s3_cache_path(str(tmp_path / "ui" / "index"), manager.get(name))
    open(path, "w").close()
    return path


def test_the_cache_action_parses(tmp_path):
    args = _args(tmp_path, "cache", "rebuild", "--workspace", "ws")
    assert args.ui_args == ["cache", "rebuild"] and args.workspace == "ws"


def test_rebuild_calls_a_running_server(tmp_path, manager, monkeypatch):
    calls = []
    monkeypatch.setattr(cache_cli, "_post", lambda url, token: calls.append((url, token)) or {})
    args = _args(tmp_path, "cache", "rebuild", "--workspace", "ws", "--token", "t")
    assert cache_cli.handle_cache(args) == 0
    assert calls == [("http://127.0.0.1:8265/api/v1/workspaces/ws/cache/resync?full=1", "t")]


def test_resync_covers_every_workspace_by_default(tmp_path, manager, monkeypatch):
    calls = []
    monkeypatch.setattr(cache_cli, "_post", lambda url, token: calls.append(url) or {})
    assert cache_cli.handle_cache(_args(tmp_path, "cache", "resync")) == 0
    assert sorted(calls) == [
        f"http://127.0.0.1:8265/api/v1/workspaces/{n}/cache/resync" for n in ("other", "ws")]


def _no_server(url, token):
    raise URLError("connection refused")


def test_rebuild_without_a_server_drops_the_cache_file(tmp_path, manager, monkeypatch):
    monkeypatch.setattr(cache_cli, "_post", _no_server)
    ws_file, other_file = (_cache_file(tmp_path, manager, n) for n in ("ws", "other"))
    assert cache_cli.handle_cache(_args(tmp_path, "cache", "rebuild", "--workspace", "ws")) == 0
    assert not os.path.exists(ws_file) and os.path.exists(other_file)


def test_resync_without_a_server_keeps_the_cache(tmp_path, manager, monkeypatch):
    monkeypatch.setattr(cache_cli, "_post", _no_server)
    path = _cache_file(tmp_path, manager, "ws")
    assert cache_cli.handle_cache(_args(tmp_path, "cache", "resync")) == 0
    assert os.path.exists(path)


def test_unknown_workspace_or_action_fails(tmp_path, manager):
    assert cache_cli.handle_cache(_args(tmp_path, "cache", "resync", "--workspace", "x")) == 1
    assert cache_cli.handle_cache(_args(tmp_path, "cache", "explode")) == 2
