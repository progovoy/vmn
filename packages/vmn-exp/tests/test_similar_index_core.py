"""The similar-runs inverted index (vmn_exp.core.similar_index): which tokens a
run is filed under, and how a query's candidates are drawn from it."""
from similar_fixtures import FakeSnapshot, changed, dataset, run
from vmn_exp.core.similar_index import CANDIDATE_CAP, SimilarIndex, index_for


def _snapshot():
    a = run(
        "a", params={"lr": 0.1}, metrics={"lr": 0.1, "val_loss": 1.0, "sys_cpu_percent": 2.0},
        inputs=dataset("imagenet@3", "sha256:1"), note="Focal loss",
    )
    b = run("b", commit="bbbbbbb", params={"opt": "adam"})
    return FakeSnapshot(
        [a, b],
        features={"a": changed(files=["src/loss.py"], symbols=["src/loss.py::focal_loss"])},
        run_states={"a": {"command": ["python", "train.py", "fit"]}},
    )


def test_a_run_is_filed_under_every_structured_signal_and_its_words():
    index = SimilarIndex(_snapshot())
    for token in ("file:src/loss.py", "sym:src/loss.py::focal_loss", "input:sha256:1",
                  "ds:imagenet", "pkey:lr", "cmd:train.py", "metric:val_loss",
                  "commit:aaaaaaa", "w:focal", "w:loss"):
        assert index.posting(token) == ("a",), token
    assert index.posting("pkey:opt") == ("b",)


def test_params_and_system_metrics_are_not_metric_tokens():
    index = SimilarIndex(_snapshot())
    assert index.posting("metric:lr") == ()
    assert index.posting("metric:sys_cpu_percent") == ()


def test_candidates_are_the_runs_sharing_a_token():
    index = SimilarIndex(_snapshot())
    assert index.candidates(["pkey:opt", "w:nothing"]) == ["b"]
    assert index.candidates(["w:nothing"]) == []


def test_candidates_come_from_the_rarest_tokens_first_up_to_the_cap():
    rows = [run(f"c{i}", params={"common": 1}) for i in range(10)]
    rows += [run("r1", params={"common": 1, "rare": 1}), run("r2", params={"rare": 1})]
    index = SimilarIndex(FakeSnapshot(rows))
    picked = index.candidates(["pkey:common", "pkey:rare"], cap=4)
    assert picked[:2] == ["r2", "r1"]
    assert len(picked) == 4
    # Past the rare runs, the newest runs of the common token fill the cap.
    assert picked[2:] == ["c9", "c8"]


def test_rejected_runs_do_not_use_up_the_cap():
    rows = [run(f"c{i}", params={"common": 1}) for i in range(10)]
    index = SimilarIndex(FakeSnapshot(rows))
    picked = index.candidates(["pkey:common"], cap=2, keep=lambda v: v not in ("c9", "c8"))
    assert picked == ["c7", "c6"]


def test_the_default_cap_is_five_thousand():
    assert CANDIDATE_CAP == 5000


def test_the_index_of_a_snapshot_is_built_once():
    snapshot = _snapshot()
    assert index_for(snapshot) is index_for(snapshot)
    assert index_for(_snapshot()) is not index_for(snapshot)


def test_a_snapshot_without_feature_accessors_still_indexes_its_rows():
    class Bare:
        rows = (run("a", params={"lr": 0.1}),)

    assert SimilarIndex(Bare()).posting("pkey:lr") == ("a",)


def test_the_index_counts_text_documents_for_bm25():
    index = SimilarIndex(_snapshot())
    assert index.bm25.n_docs == 1
    assert index.profile("a").length == 2
    assert index.profile("b").length == 0
