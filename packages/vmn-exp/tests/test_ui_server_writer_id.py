"""Edits the ui makes write log segments under the ``vmn-server`` writer id
(unless ``VMN_WRITER_ID`` names one), the id the generated edit IAM policy
allows (``runs/*/*/log/vmn-server*``, plan 11 §6.3)."""
import argparse
import os

import pytest

pytest.importorskip("fastapi")

from vmn_exp.core import writer  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402
from vmn_exp.ui.cli import server_app  # noqa: E402
from vmn_exp.ui.jobs_store import build_store_action  # noqa: E402
from vmn_exp.ui.workspaces import WorkspaceManager  # noqa: E402

APP = "app"
V = "0.0.1-dev.abc.r1"


def _serve(tmp_path):
    args = argparse.Namespace(host="127.0.0.1", read_only=False, no_index=False,
                              allowed_host=None)
    server_app(WorkspaceManager(str(tmp_path / "ui")), None, None, args, env={})


def _rewind(tmp_path):
    storage = open_storage(f"file://{tmp_path}/store", area=RUNS)
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    action, err = build_store_action("exp_rewind", APP, {"verstr": V, "step": 0})
    assert err is None
    action.run(storage, lambda app, verstr: None)
    return [name for root, _, files in os.walk(tmp_path / "store") for name in files
            if os.path.basename(root) == "log"]


def test_server_edits_use_the_server_writer_id(tmp_path, monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    monkeypatch.setattr(writer, "_WRITER_ID", "some-host")  # cached before the server
    _serve(tmp_path)
    logs = _rewind(tmp_path)
    assert logs and all("vmn-server" in name for name in logs)


def test_vmn_writer_id_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod7")
    _serve(tmp_path)
    assert writer.get_writer_id() == "pod7"
