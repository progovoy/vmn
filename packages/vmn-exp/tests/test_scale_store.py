"""scale_store: the synthetic large-store generator (plan 25 F0), read back
through the real index and reader at a small N."""
import collections
import os

import pytest
import scale_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.sdk.reader import list_runs
from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

N = 200


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("scale") / "repo")
    expected = scale_store.generate(root, N, workers=2)
    storage = open_storage(root=local_store_root(root), area="runs")
    rows = list_runs(scale_store.APP, storage=storage, include_archived=True)
    return root, expected, storage, rows


def test_every_run_reads_back(generated):
    _, expected, _, rows = generated
    assert len(rows) == N == expected["total"]
    assert len({r["verstr"] for r in rows}) == N


def test_statuses_mix_succeeded_failed_running(generated):
    _, expected, _, rows = generated
    derived = collections.Counter(r["status"] for r in rows)
    assert dict(derived) == expected["statuses"]
    assert all(derived[s] > 0 for s in ("succeeded", "failed", "running"))


def test_about_a_third_of_runs_have_parents(generated):
    _, expected, _, rows = generated
    by_verstr = {r["verstr"]: r for r in rows}
    inner = [r for r in rows if r["parent"]]
    assert len(inner) == expected["inner"]
    assert N // 4 <= len(inner) <= N // 2
    assert all(by_verstr[r["parent"]]["kind"] == "outer" for r in inner)
    assert sum(1 for r in rows if r["kind"] == "outer") == expected["outer"]


def test_runs_carry_params_and_metrics(generated):
    _, _, _, rows = generated
    finished = [r for r in rows if r["status"] in ("succeeded", "failed")]
    assert all(r["params"] and r["metrics"] for r in finished)


def test_intents_and_features_reach_the_index_side_tables(generated, tmp_path):
    root, _, storage, rows = generated
    snap = ExperimentIndex(storage, scale_store.APP,
                           cache_path=str(tmp_path / "idx.sqlite")).snapshot()
    for row in rows:
        intent = snap.intent_of(row["verstr"])
        assert 140 <= len(intent["text"].split()) <= 160
        assert len(intent["keywords"]) == 5
        changed = snap.features_of(row["verstr"])["changed"]
        assert changed["files"] and changed["symbols"]
    words = {w for row in rows for w in snap.intent_of(row["verstr"])["text"].split()}
    assert len(words) > 2000  # drawn from the 20k vocabulary, not a handful


def test_cached_returns_the_same_store_without_regenerating(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_SCALE_STORE_DIR", str(tmp_path / "cache"))
    first = scale_store.cached(30, workers=1)
    marker = os.path.join(first, scale_store.COMPLETE)
    stamp = os.stat(marker).st_mtime_ns
    assert scale_store.cached(30, workers=1) == first
    assert os.stat(marker).st_mtime_ns == stamp
    assert len(os.listdir(os.path.join(local_store_root(first), "runs", scale_store.APP))) == 30
