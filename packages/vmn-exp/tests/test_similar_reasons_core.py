"""Why a shown run is similar (vmn_exp.core.similar_reasons): per signal the
overlap of the target's and the run's filed tokens, and the reasons of the
heaviest overlaps — candidate first (``lr 3e-4 vs 1e-4`` = the run's lr vs
the target's)."""
import sqlite3

import pytest
from similar_fixtures import changed, dataset, run
from vmn_exp.core import similar_fts
from vmn_exp.core.similar_doc import build_doc
from vmn_exp.core.similar_reasons import Explainer
from vmn_exp.core.similar_weights import DEFAULT_WEIGHTS


@pytest.fixture
def explain():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    similar_fts.ensure_tables(conn)

    def explain(target, candidate, weights=DEFAULT_WEIGHTS, text_only=False):
        t = build_doc(target["row"], target.get("features"), target.get("intent"),
                      command=target.get("command"))
        c = build_doc(candidate["row"], candidate.get("features"), candidate.get("intent"),
                      command=candidate.get("command"))
        similar_fts.file_docs(conn, "app", [(c.verstr, c)])
        return Explainer(conn, t, weights, text_only).explain(c, candidate["row"],
                                                              target["row"])
    return explain


LOSS = changed(["src/loss.py", "src/a.py", "src/b.py", "src/c.py"], ["src/loss.py::focal"])


def test_a_shared_function_and_commit_lead_the_reasons(explain):
    target = {"row": run("t", commit="ccccccc"), "features": LOSS}
    reasons, signals = explain(target, {"row": run("c", commit="ccccccc"), "features": LOSS})
    assert reasons[0] == "1 shared function: loss.py::focal"
    assert "same base commit ccccccc" in reasons and len(reasons) == 3
    assert signals["symbols"] == 1.0 and signals["files"] == 1.0


def test_files_list_three_then_an_ellipsis(explain):
    target = {"row": run("t"), "features": LOSS}
    reasons, _ = explain(target, {"row": run("c"), "features": LOSS},
                         weights=dict(DEFAULT_WEIGHTS, files=50))
    assert reasons[0] == "4 shared files: src/a.py, src/b.py, src/c.py, …"


def test_params_name_the_values_that_differ_candidate_first(explain):
    target = {"row": run("t", params={"lr": 1e-4, "bs": 32})}
    reasons, signals = explain(target, {"row": run("c", params={"lr": 3e-4, "bs": 32})},
                               weights={"params": 10})
    assert reasons == ["lr 3e-4 vs 1e-4"] and 0 < signals["params"] < 1
    same, _ = explain(target, {"row": run("d", params={"lr": 1e-4, "bs": 32})},
                      weights={"params": 10})
    assert same == ["same params: bs, lr"]


def test_a_huge_integer_param_reads_as_text(explain):
    target = {"row": run("t", params={"seed": 1})}
    reasons, _ = explain(target, {"row": run("c", params={"seed": 10 ** 400})},
                         weights={"params": 1})
    assert reasons[0].startswith("seed 1000") and reasons[0].endswith("… vs 1")


def test_inputs_name_the_shared_dataset(explain):
    target = {"row": run("t", inputs=dataset("imagenet@3", "sha256:1"))}
    reasons, _ = explain(target, {"row": run("c", inputs=dataset("imagenet@3", "sha256:1"))},
                         weights={"inputs": 1})
    assert reasons == ["same dataset imagenet@3"]
    other, _ = explain(target, {"row": run("d", inputs=dataset("imagenet@4", "sha256:2"))},
                       weights={"inputs": 1})
    assert other == ["same dataset imagenet"]


def test_the_command_branch_and_metrics_are_named(explain):
    target = {"row": run("t", branch="main", metrics={"loss": 1.0}),
              "command": ["python", "train.py", "fit"]}
    candidate = {"row": run("c", branch="main", metrics={"loss": 2.0}),
                 "command": ["python", "train.py", "fit", "--x"]}
    reasons, _ = explain(target, candidate, weights={"entrypoint": 5, "branch": 2,
                                                     "objective": 1})
    assert reasons == ["same command train.py fit", "same branch main", "same metrics: loss"]


def test_two_clean_trees_say_so(explain):
    clean = {"changed": {"files": [], "symbols": []}}
    reasons, signals = explain({"row": run("t"), "features": clean},
                               {"row": run("c"), "features": clean}, weights={"files": 1})
    assert reasons == ["both clean trees"] and signals["files"] == 1.0


def test_the_text_reason_names_keyword_phrases_then_rare_shared_words(explain):
    target = {"row": run("t", note="label smoothing on noisy targets"),
              "intent": {"text": "", "keywords": ["label smoothing"]}}
    candidate = {"row": run("c", note="smoothed labels for noisy data"),
                 "intent": {"text": "", "keywords": ["label smoothing"]}}
    reasons, signals = explain(target, candidate, weights={"text": 1}, text_only=True)
    assert reasons == ["shared: label smoothing, noisy"] and set(signals) == {"text"}


def test_signals_missing_on_either_side_are_left_out(explain):
    _, signals = explain({"row": run("t", params={"a": 1})}, {"row": run("c")})
    assert "params" not in signals and "code" in signals


def test_nothing_shared_has_no_reason(explain):
    reasons, _ = explain({"row": run("t", commit="1111111", base="1.0.0")},
                         {"row": run("c", commit="2222222", base="9.0.0")})
    assert reasons == []
