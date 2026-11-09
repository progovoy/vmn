"""The submission hint over documents still behind the runs (a re-derive left
them to refile, and no server or ``vmn-exp similar`` has filed them yet) says
its runs may be incomplete instead of showing fewer without saying so."""
import argparse

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.cli import similar_hint
from vmn_exp.core import similar_fts
from vmn_exp.core.index_point import index_path
from vmn_exp.core.sqlite_conn import connect

pytestmark = pytest.mark.skipif(not similar_fts.fts5_available(),
                                reason="no SQLite FTS5 here")

CHANGES = features(["train.py"], [TRAIN_STEP], author="alice@x.io")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_SWEEP_TRIAL", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(similar_hint, "BUDGET_SEC", 60.0)


def _warm(app_layout):
    _bootstrap(app_layout)
    storage, app = _storage(app_layout), app_layout.app_name
    seed(storage, app, verstr(1, commit="0000000"), changes=CHANGES)
    assert _exp(app, action="list") == 0
    return storage, seed(storage, app, verstr(2, commit="0000000"), changes=CHANGES)


def _hint(storage, app_layout, new, capfd):
    capfd.readouterr()
    similar_hint.print_hint(storage, app_layout.app_name, new, argparse.Namespace(), {})
    return capfd.readouterr().err


def test_a_hint_over_documents_left_to_refile_says_it_may_be_incomplete(app_layout, capfd):
    storage, new = _warm(app_layout)
    conn = connect(index_path(storage, app_layout.app_name))
    conn.execute("UPDATE similar_doc SET version = 'refile:' || version")
    conn.close()
    err = _hint(storage, app_layout, new, capfd)
    assert "results incomplete" in err
    assert "vmn-exp similar" in err


def test_a_hint_over_filed_documents_says_nothing_of_it(app_layout, capfd):
    storage, new = _warm(app_layout)
    err = _hint(storage, app_layout, new, capfd)
    assert "1 similar run" in err and "incomplete" not in err
