"""Tests for the `vmn model` CLI (C7).

Seven tests — no Docker required.

1. register+list: register a model version, list models
2. alias+resolve: set alias, resolve by alias/number/latest
3. show json: model show --json produces valid JSON
4. expect mismatch: alias with --expect wrong value exits 1
5. deprecate/delete: set version status via CLI
6. delete with alias refused: delete exits 1 when alias still points to version
7. git-free mode: all commands work via VMN_EXPERIMENT_DIR (no vcs)

Tests invoke the handler functions directly (model_run_without_repo and
_handle_model_standalone) rather than through the full CLI entry point so no
Docker fixture is needed.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.registry.log import set_alias


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _run_ref(app="myapp", verstr="1.0.0"):
    return {"app": app, "verstr": verstr}


def _register_run(storage, app_name, verstr):
    """Create a stub experiment record so resolve_experiment can find verstr."""
    from version_stamp.core.experiment_writer import create_run

    params = {
        "backend": "local",
        "bucket": None,
        "prefix": "vmn-experiments",
        "endpoint_url": None,
        "experiment_dir": None,
    }
    # Minimal create_run that writes metadata and claims the verstr.
    # We use the storage directly for simplicity.
    metadata = {
        "app": app_name,
        "verstr": verstr,
        "timestamp": "2024-01-01T00:00:00.000000",
    }
    storage.create_exclusive(app_name, verstr, metadata, {})


def _make_args(**kwargs):
    """Build a SimpleNamespace of args with model CLI defaults."""
    defaults = dict(
        action=None,
        model_name=None,
        alias=None,
        alias_version=None,
        remove=False,
        version_ref=None,
        app=None,
        artifact=None,
        description=None,
        expect=None,
        json=False,
        dir=None,
        bucket=None,
        prefix="vmn-experiments",
        endpoint_url=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _invoke(tmp_path, args_kwargs, env=None):
    """Call model_run_without_repo(args) with VMN_EXPERIMENT_DIR set to tmp_path."""
    from vmn_exp.registry.cli import model_run_without_repo

    args = _make_args(dir=str(tmp_path), **args_kwargs)
    old_env = {}
    if env:
        for k, v in env.items():
            old_env[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    try:
        return model_run_without_repo(args)
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# 1. register + list
# ---------------------------------------------------------------------------

def test_register_and_list(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "1.0.0")

    rc = _invoke(tmp_path, dict(
        action="register",
        model_name="resnet",
        version_ref="1.0.0",
        app="myapp",
    ))
    assert rc == 0

    rc = _invoke(tmp_path, dict(action="list"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "resnet" in out


# ---------------------------------------------------------------------------
# 2. alias + resolve
# ---------------------------------------------------------------------------

def test_alias_and_resolve(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "1.0.0")

    # register version 1
    rc = _invoke(tmp_path, dict(
        action="register",
        model_name="resnet",
        version_ref="1.0.0",
        app="myapp",
    ))
    assert rc == 0

    # set alias prod -> 1
    rc = _invoke(tmp_path, dict(
        action="alias",
        model_name="resnet",
        alias="prod",
        alias_version="1",
    ))
    assert rc == 0

    # resolve by alias
    rc = _invoke(tmp_path, dict(action="resolve", model_name="resnet@prod"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "1.0.0" in out

    # resolve by version number
    capsys.readouterr()
    rc = _invoke(tmp_path, dict(action="resolve", model_name="resnet@1"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "1.0.0" in out

    # resolve latest (bare name)
    capsys.readouterr()
    rc = _invoke(tmp_path, dict(action="resolve", model_name="resnet"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "1.0.0" in out


# ---------------------------------------------------------------------------
# 3. show --json
# ---------------------------------------------------------------------------

def test_show_json(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "2.0.0")

    rc = _invoke(tmp_path, dict(
        action="register",
        model_name="bert",
        version_ref="2.0.0",
        app="myapp",
        description="BERT base",
    ))
    assert rc == 0
    capsys.readouterr()  # discard the "Registered ..." line

    rc = _invoke(tmp_path, dict(action="show", model_name="bert", json=True))
    assert rc == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["header"]["model"] == "bert"
    assert len(data["versions"]) == 1
    assert data["versions"][0]["n"] == 1


# ---------------------------------------------------------------------------
# 4. expect mismatch exits 1
# ---------------------------------------------------------------------------

def test_expect_mismatch_exits_1(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "1.0.0")

    _invoke(tmp_path, dict(
        action="register",
        model_name="resnet",
        version_ref="1.0.0",
        app="myapp",
    ))
    _invoke(tmp_path, dict(
        action="alias",
        model_name="resnet",
        alias="prod",
        alias_version="1",
    ))

    # expect alias points to version 99 (wrong) → should exit 1
    rc = _invoke(tmp_path, dict(
        action="alias",
        model_name="resnet",
        alias="prod",
        alias_version="1",
        expect="99",
    ))
    assert rc == 1


# ---------------------------------------------------------------------------
# 5. deprecate / delete
# ---------------------------------------------------------------------------

def test_deprecate_and_delete(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "1.0.0")

    _invoke(tmp_path, dict(
        action="register",
        model_name="resnet",
        version_ref="1.0.0",
        app="myapp",
    ))

    # deprecate version 1
    rc = _invoke(tmp_path, dict(
        action="deprecate",
        model_name="resnet",
        version_ref="1",
    ))
    assert rc == 0

    # show → deprecated status
    capsys.readouterr()  # clear "Registered..." + "Deprecated..." lines
    rc = _invoke(tmp_path, dict(action="show", model_name="resnet", json=True))
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["versions"][0]["status"] == "deprecated"

    # delete version 1 (no alias points to it)
    rc = _invoke(tmp_path, dict(
        action="delete",
        model_name="resnet",
        version_ref="1",
    ))
    assert rc == 0

    # show → deleted status
    capsys.readouterr()  # clear "Deleted..." line
    rc = _invoke(tmp_path, dict(action="show", model_name="resnet", json=True))
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["versions"][0]["status"] == "deleted"


# ---------------------------------------------------------------------------
# 6. delete with alias refused (exit 1)
# ---------------------------------------------------------------------------

def test_delete_with_alias_refused(tmp_path, capsys):
    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "1.0.0")

    _invoke(tmp_path, dict(
        action="register",
        model_name="resnet",
        version_ref="1.0.0",
        app="myapp",
    ))
    _invoke(tmp_path, dict(
        action="alias",
        model_name="resnet",
        alias="prod",
        alias_version="1",
    ))

    # delete version 1 while alias 'prod' still points to it → must fail
    rc = _invoke(tmp_path, dict(
        action="delete",
        model_name="resnet",
        version_ref="1",
    ))
    assert rc == 1


# ---------------------------------------------------------------------------
# 7. git-free mode via VMN_EXPERIMENT_DIR
# ---------------------------------------------------------------------------

def test_git_free_via_experiment_dir(tmp_path, monkeypatch, capsys):
    """model_run_without_repo works when VMN_EXPERIMENT_DIR is set (no --dir)."""
    from vmn_exp.registry.cli import model_run_without_repo

    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path))

    storage = _storage(tmp_path)
    _register_run(storage, "myapp", "3.0.0")

    # args without --dir; only VMN_EXPERIMENT_DIR is available
    args = _make_args(
        action="register",
        model_name="gpt2",
        version_ref="3.0.0",
        app="myapp",
        dir=None,  # no explicit dir
    )
    rc = model_run_without_repo(args)
    assert rc == 0

    # list works too
    args_list = _make_args(action="list", dir=None)
    rc = model_run_without_repo(args_list)
    assert rc == 0
    out = capsys.readouterr().out
    assert "gpt2" in out
