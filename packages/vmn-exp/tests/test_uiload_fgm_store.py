"""Plan 28 B0: fgm's tree seeded as a layout-2 store on disk
(:mod:`uiload.seed_fgm`), read back through the index, then served by a real
in-process ``vmn-exp ui`` and probed (:mod:`uiload.probe_fgm`): the
``experiments-status``, outer-run summary (± ``split``), grouped board and
minute-keyed waiting count requests. Only the tiny profile runs here; the
full one is the README's recipe."""
import collections
import json
import os

import pytest
from uiload import fgm_tree, probe_fgm, seed_fgm, slo
from uiload.inproc_server import serve_root
from vmn_exp.sdk.reader import list_runs
from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.store_marker import MARKER

APP = "fastglobalmacro"
STATUS = {"released": "created"}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("fgm") / "repo"
    (root / ".git").mkdir(parents=True)
    profile = fgm_tree.get_profile("fgm-tiny")
    manifest = seed_fgm.seed(str(root), profile, workers=2)
    return str(root), profile, manifest


@pytest.fixture
def live_reads_live(monkeypatch):
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", str(seed_fgm.LIVE_STALE_SEC))


def test_the_seed_writes_a_layout_2_store_and_its_manifest(seeded):
    root, profile, manifest = seeded
    specs = list(fgm_tree.plan_runs(profile, manifest["now"]))
    assert manifest["profile"] == profile.name and manifest["app"] == APP
    assert manifest["total"] == len(specs)
    assert manifest["fates"] == dict(collections.Counter(s["fate"] for s in specs))
    assert os.path.exists(os.path.join(local_store_root(root), MARKER))
    with open(os.path.join(root, seed_fgm.MANIFEST)) as f:
        assert json.load(f) == manifest


def test_the_seeded_runs_read_back_as_planned(seeded, live_reads_live):
    root, profile, manifest = seeded
    specs = {s["verstr"]: s for s in fgm_tree.plan_runs(profile, manifest["now"])}
    rows = list_runs(APP, storage=open_storage(root=local_store_root(root), area="runs"))
    assert len(rows) == len(specs)
    for row in rows:
        spec = specs[row["verstr"]]
        assert row["status"] == STATUS.get(spec["fate"], spec["fate"]), spec["name"]
        assert row["tags"] == spec["tags"] and row["parent"] == spec["parent"]
        for key, value in spec["metrics"].items():
            assert row["metrics"][key] == value
    released = [r for r in rows if specs[r["verstr"]]["fate"] == "released"]
    assert released and all(r["end_reason"] == "released" for r in released)


@pytest.mark.serial
def test_the_tiny_store_meets_its_fgm_budgets(seeded, live_reads_live, tmp_path):
    root, profile, manifest = seeded
    with serve_root(root, tmp_path / "data", "ws") as (base_url, ws):
        result = probe_fgm.measure(base_url, ws, APP, profile, expected=manifest["total"])
    assert set(result["routes"]) == set(probe_fgm.ROUTES)
    for route in probe_fgm.ROUTES:
        assert result["routes"][route]["count"] == profile.probe_requests, route
    assert result["status_total"] == manifest["total"]
    specs = list(fgm_tree.plan_runs(profile, manifest["now"]))
    live = next(s for s in specs if s["tags"]["kind"] == "launch" and s["fate"] == "running")
    assert result["live"] == live["verstr"]
    under = {s["tags"]["kind"] for s in specs if s["code_verstr"] == live["code_verstr"]}
    assert result["kinds"] == len(under - {"launch"})  # the split's values
    assert slo.fgm_evaluate(result, profile.name) == []
