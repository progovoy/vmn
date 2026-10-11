"""A cold start (``vmn-exp create|run`` on an app never stamped) reads and
checks ``--intent``/``--intent-file`` before it stamps the baseline: a bad
intent exits 1 with nothing initialized, and stdin (``-``) is read once."""
import io
import subprocess
import sys

import pytest
from exp_helpers import _PY, _exp, _storage, extract_dev_verstr


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)


def _git(app_layout, *args):
    return subprocess.run(["git", *args], cwd=app_layout.repo_path, check=True,
                          capture_output=True, text=True).stdout.split()


def _repo_state(app_layout):
    return _git(app_layout, "tag", "-l"), _git(app_layout, "rev-list", "--all")


@pytest.mark.parametrize("action, run_cmd", [("create", None), ("run", [_PY, "-c", "0"])])
def test_a_bad_intent_on_an_unstamped_app_stamps_nothing(
    app_layout, capfd, tmp_path, action, run_cmd,
):
    before = _repo_state(app_layout)
    missing = str(tmp_path / "missing.md")
    capfd.readouterr()

    rc = _exp(app_layout.app_name, action=action, run_cmd=run_cmd,
              extra_args=["--intent-file", missing])

    assert rc == 1
    assert missing in capfd.readouterr().err
    assert _repo_state(app_layout) == before


def test_an_empty_intent_on_an_unstamped_app_stamps_nothing(app_layout, capfd):
    before = _repo_state(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, extra_args=["--intent", "   "]) == 1
    assert _repo_state(app_layout) == before


def test_a_cold_start_reads_the_stdin_intent_once(app_layout, capfd, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("---\nkeywords: [gamma]\n---\nfocal loss\n"))
    capfd.readouterr()

    assert _exp(app_layout.app_name, extra_args=["--intent-file", "-"]) == 0

    verstr = extract_dev_verstr(capfd.readouterr().out)
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    [intent] = [e for e in log if e.get("type") == "intent"]
    assert intent["text"] == "focal loss" and intent["keywords"] == ["gamma"]
