"""A run's similar-runs document (vmn_exp.core.similar_doc): one token list
per signal column, the text document, and each structured token as one
opaque FTS word."""
import json

import pytest
from similar_fixtures import changed, dataset, run
from vmn_exp.core.similar_doc import COLUMNS, Doc, build_doc, word


def _doc(row=None, features=None, intent=None, **kw):
    return build_doc(row or run("a"), features, intent, None, **kw)


def test_every_column_but_text_holds_structured_tokens():
    assert COLUMNS == ("text", "code", "files", "symbols", "inputs", "params", "entry",
                       "objective", "branch")


def test_a_run_files_its_code_changes_inputs_params_command_metrics_and_branch():
    row = run("a", commit="abcdef1", base="1.2.3", params={"lr": 0.1, "opt": "adam"},
              metrics={"loss": 1.0, "lr": 0.1, "sys_cpu": 3.0}, branch="main",
              inputs=dataset("imagenet@3", "sha256:1"))
    doc = _doc(row, changed(["src/a.py"], ["src/a.py::f"]), command=["python", "train.py", "fit"])
    assert doc.cols["code"] == ("base:1.2.3", "commit:abcdef1", "line:1.2")
    assert doc.cols["files"] == ("file:src/a.py",)
    assert doc.cols["symbols"] == ("sym:src/a.py::f",)
    assert doc.cols["inputs"] == ("ds:imagenet", "input:sha256:1")
    assert doc.cols["params"] == ("pkey:lr", "pkey:opt", 'pval:lr=0.1', 'pval:opt="adam"')
    assert doc.cols["entry"] == ("args:train.py fit", "cmd:train.py", "sub:train.py fit")
    assert doc.cols["objective"] == ("metric:loss",)
    assert doc.cols["branch"] == ("branch:main",)


def test_a_clean_tree_files_a_clean_token_in_files_and_symbols():
    doc = _doc(features={"changed": {"files": [], "symbols": []}})
    assert doc.cols["files"] == ("clean:",) and doc.cols["symbols"] == ("clean:",)
    assert _doc(features=None).cols["files"] == ()


def test_the_text_holds_intent_keywords_name_note_tags_commits_and_hypothesis():
    row = run("a", name="focal", note="gamma two", tags={"team": "vision"})
    doc = build_doc(row, changed(commits=["wire loss"]), {"text": "try it", "keywords": ["Imb"]},
                    "helps recall")
    for part in ("try it", "focal", "gamma two", "team", "vision", "wire loss", "helps recall"):
        assert part in doc.text
    assert doc.text.count("imb") == 3 and doc.keywords == ("imb",)


def test_a_context_text_replaces_the_document_and_keeps_the_structure():
    doc = _doc(run("a", note="focal"), text="label smoothing")
    assert doc.text == "label smoothing" and doc.cols["code"]


def test_a_word_is_t_and_twelve_hex_digits_of_the_token():
    assert word("file:src/a.py") == word("file:src/a.py")
    assert word("file:src/a.py") != word("file:src/b.py")
    assert len(word("x")) == 13 and word("x")[0] == "t"
    int(word("x")[1:], 16)


def test_fts_values_put_text_first_then_one_word_per_structured_token():
    doc = _doc(run("a", branch="dev"))
    values = doc.fts_values()
    assert len(values) == len(COLUMNS) and values[0] == doc.text
    assert values[COLUMNS.index("branch")] == word("branch:dev")


def test_a_doc_round_trips_through_its_stored_data():
    doc = _doc(run("a", params={"lr": 1}), changed(["x.py"]), {"text": "t", "keywords": ["k"]})
    again = Doc.from_data("a", doc.rerun, json.loads(json.dumps(doc.data())), doc.text)
    assert (again.cols, again.keywords, again.rerun) == (doc.cols, doc.keywords, doc.rerun)


def test_the_rerun_key_is_the_profiles():
    assert _doc(run("a", code="c1")).rerun == _doc(run("b", code="c1")).rerun
    assert _doc(run("a", code="c1")).rerun != _doc(run("a", code="c2")).rerun


@pytest.mark.parametrize("value", [float("nan"), [1, 2], {"a": 1}, None])
def test_a_param_value_that_is_no_scalar_files_its_key_only(value):
    doc = _doc(run("a", params={"x": value}))
    assert doc.cols["params"] == ("pkey:x",)


def test_the_base_version_is_kept_for_reasons_but_never_filed_for_matching():
    doc = _doc(run("a", commit="abcdef1", base="1.2.3"))
    assert "base:1.2.3" in doc.cols["code"]
    assert doc.fts_values()[COLUMNS.index("code")] == word("commit:abcdef1")
