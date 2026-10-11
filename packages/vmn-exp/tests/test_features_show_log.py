"""``vmn-exp show`` lists a run's log events: the ``features`` entry records
facts about the run, not an event, so the text and ``--json`` logs (and
``log_total``) leave it out and ``--json`` carries it as ``features``."""
import json
import os

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    vmn_logging.ensure_logger()
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)


def _run_with_features(app_layout):
    _bootstrap(app_layout)
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write("def train():\n    pass\n")
    assert _exp(app_layout.app_name, note="first") == 0
    (verstr,) = _storage(app_layout).list_record_names(app_layout.app_name)
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    assert [e["type"] for e in log] == ["create", "features"]
    return verstr


def _show(capfd, app_layout, verstr, extra_args=None):
    capfd.readouterr()
    rc = _exp(app_layout.app_name, action="show", version=verstr, extra_args=extra_args)
    assert rc == 0
    return capfd.readouterr().out


def test_show_lists_the_log_without_the_features_entry(app_layout, capfd):
    out = _show(capfd, app_layout, _run_with_features(app_layout))
    assert "Log (1 entries)" in out
    log_lines = out.split("Log (", 1)[1].splitlines()[1:]
    assert len(log_lines) == 1 and "created: first" in log_lines[0]


def test_show_json_leaves_the_features_entry_out_of_the_log(app_layout, capfd):
    verstr = _run_with_features(app_layout)
    run = json.loads(_show(capfd, app_layout, verstr, ["--json"]))
    assert [e["type"] for e in run["log"]] == ["create"]
    assert run["log_total"] == 1


def test_show_json_carries_the_runs_features(app_layout, capfd):
    verstr = _run_with_features(app_layout)
    run = json.loads(_show(capfd, app_layout, verstr, ["--json"]))
    assert run["features"]["source"] == "capture"
    assert run["features"]["changed"]["untracked"] == ["train.py"]
