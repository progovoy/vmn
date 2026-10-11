"""At 20k runs, what the UI does per index generation stays cheap: a heartbeat
(run states only) reuses the similar index outright, a few changed runs cost
their own profiles, and four concurrent requests on a new generation build it
once — where each used to pay a whole build."""
import random
import threading
import time

import pytest
from similar_fixtures import FakeSnapshot, changed, dataset, run
from vmn_exp.core import similar_index
from vmn_exp.core.similar import similar_runs_multi
from vmn_exp.core.similar_cache import IndexLineages

RUNS = 20000
WORDS = ("focal loss label smoothing mixup cutout warmup cosine schedule adam sgd "
         "dropout weight decay imbalance recall precision augmentation distill").split()


def _rows_and_features(n, seed=11):
    rnd = random.Random(seed)
    rows, features = [], {}
    for i in range(n):
        verstr = f"1.{i % 40}.0-dev.{i % 97:07d}.{i:07d}"
        rows.append(run(
            verstr, base=f"1.{i % 40}.0", note=" ".join(rnd.sample(WORDS, 4)),
            params={"lr": rnd.choice([1e-4, 3e-4]), f"p{i % 30}": i % 5},
            metrics={"val_loss": rnd.random(), f"m{i % 20}": 1.0},
            inputs=dataset(f"ds{i % 15}@1", f"sha256:{i % 60}"), tags={"team": f"t{i % 9}"},
            command=["python", "train.py"],
        ))
        features[verstr] = changed(
            files=[f"src/m{i % 120}.py", f"src/m{(i * 7) % 120}.py"],
            symbols=[f"src/m{i % 120}.py::f{i % 300}"], commits=[" ".join(rnd.sample(WORDS, 3))])
    return rows, features


@pytest.fixture(scope="module")
def corpus():
    return _rows_and_features(RUNS)


@pytest.fixture
def built(monkeypatch):
    calls, real = [], similar_index.build_profile

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_index, "build_profile", counted)
    return calls


def _snapshot(rows, features, beat):
    return FakeSnapshot(rows, features=features, run_states={rows[0]["verstr"]: {"heartbeat": beat}})


def _warm(lineages, snapshot):
    return lineages.index_for("app", snapshot, deadline=time.monotonic() + 60)


def test_a_heartbeat_generation_reuses_the_index_without_a_rebuild(corpus, built):
    rows, features = corpus
    lineages = IndexLineages()
    first = _warm(lineages, _snapshot(rows, features, 1))
    built.clear()
    started = time.perf_counter()
    again = _warm(lineages, _snapshot(rows, features, 2))
    elapsed = time.perf_counter() - started
    assert again is first and built == []
    assert elapsed < 0.5, elapsed


def test_a_few_changed_runs_reindex_in_a_fraction_of_a_build(corpus, built):
    rows, features = corpus
    lineages = IndexLineages()
    started = time.perf_counter()
    _warm(lineages, _snapshot(rows, features, 1))
    cold = time.perf_counter() - started
    rows = list(rows)
    rows[100] = dict(rows[100], metrics={"val_loss": 0.01})
    rows.append(run("1.0.0-dev.new", params={"lr": 1e-4}, note="focal loss again"))
    built.clear()
    started = time.perf_counter()
    _warm(lineages, _snapshot(rows, features, 2))
    warm = time.perf_counter() - started
    assert len(built) == 2
    assert warm < max(0.5, cold / 3), (warm, cold)


def test_four_concurrent_requests_on_a_new_generation_build_it_once(corpus, built):
    rows, features = corpus
    lineages = IndexLineages()
    snapshot = _snapshot(rows, features, 1)
    target = {"row": None, "text": "focal loss imbalance", "text_only": True}
    barrier, answers = threading.Barrier(4), []

    def request():
        barrier.wait()
        _warm(lineages, snapshot)
        answers.append(similar_runs_multi([("app", snapshot, None)], target, top=5))

    threads = [threading.Thread(target=request) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(answers) == 4 and all(a == answers[0] for a in answers)
    assert len(built) == RUNS
