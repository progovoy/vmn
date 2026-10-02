"""uiload seeder: bulk historical runs, read back through the real readers."""
import collections
import math
import os
import time
from types import SimpleNamespace

import pytest
from uiload import seeder
from vmn_exp.core.tree import rollup_status
from vmn_exp.sdk.reader import list_runs
from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

APP = "loadapp"
STATUSES = ("succeeded", "failed", "stuck", "created")


def _root(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return str(root)


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = _root(tmp_path_factory.mktemp("seed"))
    counts = seeder.seed(
        root, runs=60, sweeps=2, inner_per_sweep=5, max_metric_keys=30,
        max_steps=500, max_params=20, rng_seed=7, workers=2,
    )
    storage = open_storage(root=local_store_root(root), area="runs")
    rows = list_runs(APP, storage=storage, include_archived=True)
    return root, counts, storage, rows


def test_counts_add_up(seeded):
    _, counts, _, rows = seeded
    assert counts["total"] == 60 == len(rows)
    assert sum(counts[s] for s in STATUSES) == 60
    assert counts["outer"] == 2 and counts["inner"] == 10
    assert all(counts[s] > 0 for s in ("succeeded", "failed"))


def test_derived_statuses_match_the_returned_counts(seeded):
    _, counts, _, rows = seeded
    derived = collections.Counter(r["status"] for r in rows)
    assert {s: derived[s] for s in STATUSES} == {s: counts[s] for s in STATUSES}


def test_every_run_is_named_and_uniquely_versioned(seeded):
    _, _, _, rows = seeded
    names = sorted(r["name"] for r in rows)
    assert names == [f"hist-{i:06d}" for i in range(60)]
    assert len({r["verstr"] for r in rows}) == 60
    for r in rows:
        assert "-dev." in r["verstr"]
        suffix = r["verstr"][len(r["code_verstr"]):]
        assert suffix == "" or (suffix.startswith(".r") and suffix[2:].isdigit())


def test_sweeps_link_inner_runs_to_their_outer(seeded):
    _, _, _, rows = seeded
    by_verstr = {r["verstr"]: r for r in rows}
    outers = [r for r in rows if r["kind"] == "outer"]
    assert len(outers) == 2
    for outer in outers:
        assert len(outer["children"]) == 5
        kids = [by_verstr[v] for v in outer["children"]]
        assert all(k["kind"] == "inner" and k["parent"] == outer["verstr"] for k in kids)
        expected = rollup_status([outer["status"]] + [k["status"] for k in kids])
        assert outer["tree_status"] == expected
    assert collections.Counter(r["kind"] for r in rows)["inner"] == 10


def test_metrics_and_params_come_through(seeded):
    _, _, _, rows = seeded
    finished = [r for r in rows if r["status"] in ("succeeded", "failed")]
    assert all(r["metrics"] and r["params"] for r in finished)
    kinds = {type(v) for r in rows for v in r["params"].values()}
    assert {float, int, str, bool} <= kinds
    assert all(len(r["params"]) <= 20 for r in rows)
    assert all(len([k for k in r["metrics"] if k not in r["params"]]) <= 30 for r in rows)


def test_params_query_selects_by_string_param(seeded):
    _, _, storage, rows = seeded
    want = {r["verstr"] for r in rows if r["params"].get("optimizer") == "adam"}
    assert want
    got = list_runs(APP, storage=storage, include_archived=True,
                    query='params.optimizer = "adam"')
    assert {r["verstr"] for r in got} == want


def test_some_runs_are_archived_and_hidden_by_default(seeded):
    _, counts, storage, rows = seeded
    archived = [r for r in rows if r["archived"]]
    assert len(archived) == counts["archived"] > 0
    assert len(list_runs(APP, storage=storage)) == 60 - counts["archived"]
    assert any(r["tags"] for r in rows)


def test_long_series_exist_for_downsampling(tmp_path):
    root = _root(tmp_path)
    seeder.seed(root, runs=300, sweeps=0, inner_per_sweep=0, max_metric_keys=10,
                max_steps=5000, max_params=10, workers=1)
    logs = []
    base = os.path.join(root, ".vmn", "store", "runs", APP)
    for verstr in os.listdir(base):
        folder = os.path.join(base, verstr, "log")
        if os.path.isdir(folder):
            logs.append(sum(sum(1 for _ in open(os.path.join(folder, f)))
                            for f in os.listdir(folder) if f.endswith(".jsonl")))
    logs.sort()
    assert logs[len(logs) // 2] <= 250  # most runs are short
    assert logs[-1] > 2000  # the tail is long


def test_ui_api_lists_all_seeded_runs(seeded):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root, counts, _, _ = seeded
    manager = WorkspaceManager(os.path.join(os.path.dirname(root), "uidata"))
    manager.attach_path("ws", root)
    client = TestClient(create_app(manager))
    base = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
    page = client.get(f"{base}?limit=1000&archived=1").json()
    assert page["total"] == 60
    statuses = collections.Counter(r["status"] for r in page["rows"])
    assert {s: statuses[s] for s in STATUSES} == {s: counts[s] for s in STATUSES}
    assert client.get(f"{base}?limit=1000").json()["total"] == 60 - counts["archived"]


def test_nan_and_inf_metrics_are_kept_somewhere(tmp_path):
    root = _root(tmp_path)
    seeder.seed(root, runs=400, sweeps=0, inner_per_sweep=0, max_metric_keys=10,
                max_steps=50, max_params=5, workers=1)
    storage = open_storage(root=local_store_root(root), area="runs")
    values = [v for r in list_runs(APP, storage=storage, include_archived=True)
              for v in r["metrics"].values()]
    assert any(isinstance(v, float) and not math.isfinite(v) for v in values)


def test_seed_profile_reads_profile_fields(tmp_path):
    root = _root(tmp_path)
    profile = SimpleNamespace(seeded_runs=20, seeded_sweeps=1, seeded_inner_per_sweep=3,
                              max_metric_keys=5, max_steps=30, max_params=5)
    counts = seeder.seed_profile(root, profile)
    assert counts["total"] == 20 and counts["outer"] == 1 and counts["inner"] == 3


def test_seeding_is_deterministic(tmp_path):
    kw = dict(runs=50, sweeps=1, inner_per_sweep=4, max_metric_keys=5, max_steps=30,
              max_params=5, rng_seed=3, workers=1)
    a = seeder.seed(_root(tmp_path / "a"), **kw)
    b = seeder.seed(_root(tmp_path / "b"), **dict(kw, workers=3))
    assert a == b


def test_two_thousand_runs_seed_fast(tmp_path):
    root = _root(tmp_path)
    start = time.monotonic()
    counts = seeder.seed(root, runs=2000, sweeps=10, inner_per_sweep=20,
                         max_metric_keys=50, max_steps=10000, max_params=30)
    assert counts["total"] == 2000
    assert time.monotonic() - start < 10
