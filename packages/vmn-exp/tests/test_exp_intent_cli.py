"""``--intent "<text>"`` / ``--intent-file <path|->`` on ``vmn-exp create|run|add``.

create/run append an ``intent`` entry after the run's create entry; add appends
one to the resolved run (the latest without ``-v``, like ``--note``), where the
latest intent wins. A bad intent input is refused before anything is written.
"""
import io
import json
import sys

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage, extract_dev_verstr
from vmn_exp.core.fold import fold_intent, fold_log

INTENT_MD = (
    "---\n"
    "keywords: [focal loss, Gamma, gamma]\n"
    "generator: claude-opus-5-5\n"
    "---\n"
    "Try focal loss (gamma=2) on the long tail.\n"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _intents(app_layout, verstr):
    return [e for e in _log(app_layout, verstr) if e.get("type") == "intent"]


def _runs(app_layout):
    return [r["verstr"] for r in _storage(app_layout).list_snapshots(app_layout.app_name)]


def _create(app_layout, capfd, *extra):
    capfd.readouterr()
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _intent_file(tmp_path, content=INTENT_MD):
    path = tmp_path / "intent.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


# -- create ---------------------------------------------------------------------


def test_create_with_intent_records_it_after_the_create_entry(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd, "--intent", "focal loss for the long tail")

    log = _log(app_layout, verstr)
    types = [e.get("type") for e in log]
    assert types.index("create") < types.index("intent")
    [entry] = _intents(app_layout, verstr)
    assert entry["text"] == "focal loss for the long tail"
    assert entry["source"] == "user"
    assert entry["timestamp"]
    assert fold_intent(fold_log(log))["text"] == "focal loss for the long tail"


def test_create_with_intent_file_reads_its_front_matter(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd, "--intent-file", _intent_file(tmp_path))

    [entry] = _intents(app_layout, verstr)
    assert entry["text"] == "Try focal loss (gamma=2) on the long tail."
    assert entry["keywords"] == ["focal loss", "Gamma"]
    assert entry["generator"] == "claude-opus-5-5"


def test_intent_file_dash_reads_stdin(app_layout, capfd, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setattr(sys, "stdin", io.StringIO(INTENT_MD))
    verstr = _create(app_layout, capfd, "--intent-file", "-")

    [entry] = _intents(app_layout, verstr)
    assert entry["text"] == "Try focal loss (gamma=2) on the long tail."
    assert entry["generator"] == "claude-opus-5-5"


def test_create_without_intent_records_none(app_layout, capfd):
    _bootstrap(app_layout)
    assert _intents(app_layout, _create(app_layout, capfd)) == []


def test_intent_and_intent_file_are_mutually_exclusive(app_layout, tmp_path):
    _bootstrap(app_layout)
    with pytest.raises(SystemExit):
        _exp(app_layout.app_name,
             extra_args=["--intent", "x", "--intent-file", _intent_file(tmp_path)])


def test_an_unreadable_intent_file_creates_no_run(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    missing = str(tmp_path / "missing.md")
    capfd.readouterr()
    assert _exp(app_layout.app_name, extra_args=["--intent-file", missing]) == 1
    assert missing in capfd.readouterr().err
    assert _runs(app_layout) == []


@pytest.mark.parametrize("content", ["", "---\nkeywords: [a]\n---\n  \n"])
def test_an_empty_intent_creates_no_run(app_layout, capfd, tmp_path, content):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name,
                extra_args=["--intent-file", _intent_file(tmp_path, content)]) == 1
    assert "intent" in capfd.readouterr().err
    assert _runs(app_layout) == []


def test_bad_front_matter_creates_no_run(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    bad = _intent_file(tmp_path, "---\nkeywords: [unclosed\n---\ntext\n")
    capfd.readouterr()
    assert _exp(app_layout.app_name, extra_args=["--intent-file", bad]) == 1
    assert "front matter" in capfd.readouterr().err
    assert _runs(app_layout) == []


# -- run ------------------------------------------------------------------------


def test_run_with_intent_file_records_it(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name, action="run",
                extra_args=["--intent-file", _intent_file(tmp_path)],
                run_cmd=[sys.executable, "-c", "pass"]) == 0

    [verstr] = _runs(app_layout)
    [entry] = _intents(app_layout, verstr)
    assert entry["keywords"] == ["focal loss", "Gamma"]


def test_run_with_a_bad_intent_creates_no_run(app_layout, tmp_path):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name, action="run",
                extra_args=["--intent-file", str(tmp_path / "missing.md")],
                run_cmd=[sys.executable, "-c", "pass"]) == 1
    assert _runs(app_layout) == []


# -- add ------------------------------------------------------------------------


def test_add_intent_without_a_version_targets_the_latest_run(app_layout, capfd):
    _bootstrap(app_layout)
    first = _create(app_layout, capfd)
    latest = _create(app_layout, capfd)

    assert _exp(app_layout.app_name, action="add", extra_args=["--intent", "later"]) == 0
    assert f"Added intent to {latest}" in capfd.readouterr().out
    assert [e["text"] for e in _intents(app_layout, latest)] == ["later"]
    assert _intents(app_layout, first) == []


def test_add_intent_file_on_a_named_run_replaces_its_intent(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    first = _create(app_layout, capfd, "--intent", "first idea")
    _create(app_layout, capfd)

    assert _exp(app_layout.app_name, action="add", version=first,
                extra_args=["--intent-file", _intent_file(tmp_path)]) == 0
    assert len(_intents(app_layout, first)) == 2
    folded = fold_intent(fold_log(_log(app_layout, first)))
    assert folded["text"] == "Try focal loss (gamma=2) on the long tail."
    assert folded["keywords"] == ["focal loss", "Gamma"]


def test_add_with_a_bad_intent_writes_nothing(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    verstr = _create(app_layout, capfd)
    before = _log(app_layout, verstr)

    assert _exp(app_layout.app_name, action="add", version=verstr,
                extra_args=["--note", "n", "--intent-file", str(tmp_path / "no.md")]) == 1
    assert _log(app_layout, verstr) == before


# -- has_intent, end to end -----------------------------------------------------


def _listed(app_layout, capfd, query):
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list",
                extra_args=["--query", query, "--json"]) == 0
    return [row["verstr"] for row in json.loads(capfd.readouterr().out)]


def test_has_intent_selects_runs_created_with_an_intent_file(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    with_intent = _create(app_layout, capfd, "--intent-file", _intent_file(tmp_path))
    without = _create(app_layout, capfd)

    assert _listed(app_layout, capfd, "has_intent = true") == [with_intent]
    assert _listed(app_layout, capfd, "has_intent = false") == [without]


# -- git-free (VMN_SNAPSHOT_METADATA) -------------------------------------------


def test_git_free_create_records_the_intent(tmp_path, monkeypatch, capfd):
    from vmn_exp.cli.main import vmn_exp_run

    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(yaml.safe_dump(
        {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": "trainer",
         "base_version": "1.2.0", "base_commit": "abc1234"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(meta))
    store = ["--experiment-dir", str(tmp_path / "store")]

    assert vmn_exp_run(["exp", "create", "trainer", *store, "--intent", "container idea"])[0] == 0
    assert vmn_exp_run(["exp", "create", "trainer", *store])[0] == 0
    capfd.readouterr()
    assert vmn_exp_run(["exp", "list", "trainer", *store,
                        "--query", "has_intent = true", "--json"])[0] == 0
    [row] = json.loads(capfd.readouterr().out)
    assert row["has_intent"] is True
    capfd.readouterr()
    assert vmn_exp_run(["exp", "show", "trainer", "-v", row["verstr"], *store,
                        "--json"])[0] == 0
    shown = json.loads(capfd.readouterr().out)
    assert [e["text"] for e in shown["log"] if e.get("type") == "intent"] == [
        "container idea"]
