"""``vmn-exp ui`` on an S3 store without boto3 (the ``s3`` extra) refuses to
start with the install hint, rather than serving and answering 500 "No module
named boto3" on the first request (plan 31 §4.4)."""
import importlib.util

import pytest

pytest.importorskip("fastapi")

from test_ui_cli import _run_handle_ui  # noqa: E402

HINT = 'pip install "vmn-exp[ui,s3]"'


@pytest.fixture
def no_boto3(monkeypatch):
    real = importlib.util.find_spec

    def find_spec(name, *args, **kwargs):
        if name == "boto3" or name.startswith("boto3."):
            return None
        return real(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", find_spec)


def _server_yml(tmp_path, store):
    path = tmp_path / "server.yml"
    path.write_text(f"data_dir: {tmp_path / 'data'}\n"
                    f"workspaces:\n  - name: team\n    store: {store}\n")
    return str(path)


def test_an_s3_store_without_boto3_refuses_to_start(tmp_path, monkeypatch, capfd, no_boto3):
    rc, calls = _run_handle_ui(tmp_path, monkeypatch, ["--store", "s3://bkt/team"])

    assert rc != 0
    assert calls == []
    assert HINT in capfd.readouterr().err


def test_a_server_yml_s3_workspace_without_boto3_refuses_to_start(
        tmp_path, monkeypatch, capfd, no_boto3):
    rc, calls = _run_handle_ui(
        tmp_path, monkeypatch, ["--config", _server_yml(tmp_path, "s3://bkt/team")])

    assert rc != 0
    assert calls == []
    assert HINT in capfd.readouterr().err


def test_a_file_store_without_boto3_still_starts(tmp_path, monkeypatch, capfd, no_boto3):
    store = tmp_path / "store"
    store.mkdir()
    rc, calls = _run_handle_ui(
        tmp_path, monkeypatch, ["--config", _server_yml(tmp_path, f"file://{store}")])

    assert rc == 0
    assert len(calls) == 1
    calls[0][0][0].state.refresher.stop()
