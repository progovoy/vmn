"""Plan 28 B0: fgm's tree seeded as a layout-2 store on disk
(:mod:`uiload.seed_fgm`), read back through the index, then served by a real
in-process ``vmn-exp ui`` and probed (:mod:`uiload.probe_fgm`): the
``experiments-status``, outer-run summary (± ``split``), grouped board and
minute-keyed waiting count requests. Only the tiny profile runs here; the
full one is the README's recipe."""
import collections
import datetime
import json
import os

import pytest
from uiload import fgm_records, fgm_tree, probe_fgm, seed_fgm, slo
from uiload.inproc_server import serve_root
from vmn_exp.core.app_settings_store import read_settings
from vmn_exp.core.status import derive_status
from vmn_exp.sdk.reader import list_runs
from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root
from vmn_exp.storage.store_marker import MARKER

APP = fgm_records.APP
NOW = 1_800_000_000.0


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("fgm") / "repo"
    (root / ".git").mkdir(parents=True)
    profile = fgm_tree.get_profile("fgm-tiny")
    manifest = seed_fgm.seed(str(root), profile, workers=2)
    return str(root), profile, manifest


def test_seeded_live_runs_stay_running_and_orphans_stay_stuck():
    """Served long after seeding, with the default stale floor."""
    full = fgm_tree.get_profile("fgm")
    specs = fgm_tree.launch_runs(full, 0, NOW) + fgm_tree.launch_runs(full, full.launches - 1, NOW)
    later = datetime.datetime.fromtimestamp(NOW + 30 * 86400, datetime.timezone.utc)
    seen = collections.Counter()
    for spec in (s for s in specs if s["fate"] in ("running", "stuck")):
        state = seed_fgm.seeded_run_state(spec, NOW)
        seen[spec["fate"]] += 1
        assert derive_status(state, now=later) == spec["fate"]
    assert seen["running"] and seen["stuck"]


def test_the_seed_writes_a_layout_2_store_and_its_manifest(seeded):
    root, profile, manifest = seeded
    specs = list(fgm_tree.plan_runs(profile, manifest["now"]))
    assert manifest["profile"] == profile.name and manifest["app"] == APP
    assert manifest["total"] == len(specs)
    assert manifest["fates"] == dict(collections.Counter(s["fate"] for s in specs))
    assert os.path.exists(os.path.join(local_store_root(root), MARKER))
    with open(os.path.join(root, seed_fgm.MANIFEST)) as f:
        assert json.load(f) == manifest


def test_the_seeded_runs_read_back_as_planned(seeded):
    root, profile, manifest = seeded
    specs = {s["verstr"]: s for s in fgm_tree.plan_runs(profile, manifest["now"])}
    rows = list_runs(APP, storage=open_storage(root=local_store_root(root), area="runs"))
    assert len(rows) == len(specs)
    for row in rows:
        spec = specs[row["verstr"]]
        assert row["status"] == fgm_tree.derived_status(spec["fate"]), spec["name"]
        assert row["tags"] == spec["tags"] and row["parent"] == spec["parent"]
        for key, value in spec["metrics"].items():
            assert row["metrics"][key] == value
    released = [r for r in rows if specs[r["verstr"]]["fate"] == "released"]
    assert released and all(r["end_reason"] == "released" for r in released)


@pytest.mark.serial
def test_the_tiny_store_meets_its_fgm_budgets(seeded, tmp_path):
    root, profile, manifest = seeded
    with serve_root(root, tmp_path / "data", "ws") as (base_url, ws):
        result = probe_fgm.measure(base_url, ws, APP, profile, expected=manifest["total"])
    assert set(result["routes"]) == set(probe_fgm.ROUTES)
    for route in probe_fgm.ROUTES:
        assert result["routes"][route]["count"] == profile.probe_requests, route
    assert result["status_total"] == manifest["total"]
    specs = list(fgm_tree.plan_runs(profile, manifest["now"]))
    live, _ = fgm_tree.launches(specs)
    assert result["live"] == live
    under = {s["tags"]["kind"] for s in specs if s["code_verstr"] == live}  # its first run
    assert result["kinds"] == len(under - {"launch"})  # the split's values
    assert slo.fgm_evaluate(result, profile.name) == []


def test_the_seed_writes_fgm_like_store_settings(seeded):
    """P1's attention queries and P3's split reach the server through A0."""
    root, _, _ = seeded
    ui = read_settings(open_storage(root=local_store_root(root), area="runs"), APP)["ui"]
    assert ui["split_by"] == "tags.kind"
    queries = {entry["key"]: entry["query"] for entry in ui["attention"]}
    assert queries["waiting"] == probe_fgm.WAITING


def test_the_cold_waiting_count_asks_a_minute_no_status_poll_pinned():
    """Waiting for the index polls ``experiments-status``, whose seeded
    attention query already built the ``ago("1h")`` order."""
    _, params = probe_fgm.cold_waiting("/ws")
    assert params["q"] == 'status = "created" and timestamp < ago("59m")'
    assert 'ago("1h")' in probe_fgm.WAITING


def test_each_waiting_request_pins_to_its_own_minute():
    """The status route warms the 1 h order (the seeded attention query), so
    each timed request asks for another minute: every one rebuilds."""
    waiting = probe_fgm._requests("/ws", "live", "ended")["waiting"]
    queries = [waiting(i)[1]["q"] for i in range(20)]
    assert len(set(queries)) == 20
    assert all('ago("' in q and q.startswith('status = "created"') for q in queries)
    assert 'ago("1h")' not in "".join(queries) and 'ago("60m")' not in "".join(queries)


@pytest.mark.serial
def test_the_probe_reads_the_seeded_settings_back(seeded, tmp_path):
    root, profile, manifest = seeded
    with serve_root(root, tmp_path / "data", "ws") as (base_url, ws):
        result = probe_fgm.measure(base_url, ws, APP, profile, expected=manifest["total"])
    keys = [entry["key"] for entry in seed_fgm.SETTINGS["ui"]["attention"]]
    assert sorted(result["attention"]) == sorted(keys)
    assert all(isinstance(n, int) for n in result["attention"].values()), result["attention"]
    assert result["attention"]["waiting"] > 0
    assert result["default_split"] == "tags.kind"


@pytest.mark.serial
def test_the_probe_times_a_cold_waiting_count_before_status(seeded, tmp_path):
    root, profile, manifest = seeded
    with serve_root(root, tmp_path / "data", "ws") as (base_url, ws):
        result = probe_fgm.measure(base_url, ws, APP, profile, expected=manifest["total"])
    assert result["waiting_cold_ms"] > 0
