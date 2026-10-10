"""``author`` and ``has_intent`` in the query language.

Both are plain row fields, so ``--query`` filters on them in Python, the
Postgres search backend compiles them like any bare field, and the web ui's
autocomplete lists them. ``has_intent`` is a real bool on every row, so
``has_intent = false`` (an agent's backfill worklist) finds runs without one.
"""
import json
import os

import pytest
from exp_helpers import _exp, _storage
from vmn_exp.core.log import experiment_row
from vmn_exp.core.query import ROW_FIELDS, QueryError, filter_rows
from vmn_exp.ui.query_sql import compile_sql

META = {"timestamp": "2026-01-01T00:00:00Z"}


def _features(author):
    return {"timestamp": "t1", "type": "features", "features_version": 1, "author": author}


def _rows():
    intent = {"timestamp": "t2", "type": "intent", "text": "focal loss"}
    return [
        experiment_row(1, dict(META, verstr="a"),
                       [_features({"git_user_email": "alice@x.io", "os_user": "alice"}), intent]),
        experiment_row(2, dict(META, verstr="b"), [_features({"os_user": "bob"})]),
        experiment_row(3, dict(META, verstr="c"), []),
    ]


def _verstrs(text):
    return [r["verstr"] for r in filter_rows(_rows(), text)]


def test_both_fields_are_query_fields():
    assert {"author", "has_intent"} <= ROW_FIELDS


@pytest.mark.parametrize("text, expected", [
    ('author = "alice@x.io"', ["a"]),
    ('author ~ "BOB"', ["b"]),
    ('author in ("bob", "carol")', ["b"]),
    ("author = null", ["c"]),
    ('author != "bob"', ["a", "c"]),
    ("has_intent = true", ["a"]),
    ("has_intent = false", ["b", "c"]),
    ("not has_intent = true", ["b", "c"]),
    ("has_intent = false and author ~ \"bob\"", ["b"]),
])
def test_queries_filter_on_author_and_has_intent(text, expected):
    assert _verstrs(text) == expected


def test_a_misspelled_field_is_still_an_error():
    with pytest.raises(QueryError):
        filter_rows(_rows(), "has_intents = true")


def test_sql_compiles_has_intent_against_a_jsonb_boolean():
    where, params = compile_sql("has_intent = false")
    assert ["has_intent"] in params.values()
    assert json.dumps(False) in params.values()
    assert "::jsonb" in where and "COALESCE" in where


def test_sql_compiles_author_against_a_jsonb_string():
    where, params = compile_sql('author = "x@y.io"')
    assert ["author"] in params.values()
    assert json.dumps("x@y.io") in params.values()
    assert "::jsonb" in where


def test_webui_query_suggest_knows_author_and_has_intent():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    path = os.path.join(root, "packages", "vmn-exp", "webui", "src", "util", "querySuggest.ts")
    with open(path) as f:
        source = f.read()
    fields = source.split("ROW_FIELDS = [", 1)[1].split("]", 1)[0]
    assert '"author"' in fields and '"has_intent"' in fields


def test_cli_list_worklist_finds_runs_without_an_intent(app_layout, capfd):
    storage, app = _storage(app_layout), app_layout.app_name
    for verstr, entries in (("0.0.1-dev.a", [_features({"os_user": "alice"})]),
                            ("0.0.1-dev.b", [{"timestamp": "t2", "type": "intent", "text": "x"}])):
        storage.save(app, verstr, dict(META, verstr=verstr), {})
        for entry in [{"timestamp": "t0", "type": "create", "params": {}}] + entries:
            storage.append_log_entry(app, verstr, "w", entry)
    capfd.readouterr()
    code = _exp(app, action="list", extra_args=["--query", "has_intent = false", "--json"])
    out = capfd.readouterr()
    assert code == 0, out.err
    rows = json.loads(out.out)
    assert [(r["verstr"], r["author"], r["has_intent"]) for r in rows] == [
        ("0.0.1-dev.a", "alice", False)]
