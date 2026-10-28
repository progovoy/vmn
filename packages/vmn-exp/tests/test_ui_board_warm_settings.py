"""The board warm-up sorts and rolls up by what a request does: the app's
conf / store settings schema plus what its runs declare, and its
``ui.progress`` names (plan 28 A0) — so a store with settings still gets its
default pages warm."""
from test_ui_board_warm import DEFAULT, TOPS, _Builds, _fleet, frozen  # noqa: F401
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.ui.job_rollup_cache import JobRollupCache
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min"}, "acc": {"goal": "max"}}
UI = {"progress": {"done": "acc", "total": "loss"}}


def _request_inputs(snap):
    board = snap.summarized(SCHEMA)
    return board, effective_schema(SCHEMA, board.declared_schema())


def test_a_warmed_generation_answers_a_request_under_the_apps_settings(frozen, monkeypatch):
    snap = _fleet().snapshot()
    cache = LeaderboardCache(conf_of=lambda s: (SCHEMA, UI))
    builds = _Builds(monkeypatch)
    compute = JobRollupCache._compute
    monkeypatch.setattr(JobRollupCache, "_compute",
                        lambda s, *a: builds.calls.append("rollup") or compute(s, *a))
    cache.warm(snap)
    builds.calls.clear()
    board, schema = _request_inputs(snap)
    for top in TOPS:
        assert cache.page(board, schema, top=top, **DEFAULT)["rows"], top
    cache.facets_payload(board)
    assert builds.calls == []


def test_without_settings_the_warm_up_sorts_by_what_runs_declare(frozen, monkeypatch):
    snap = _fleet().snapshot()
    cache = LeaderboardCache()
    cache.warm(snap)
    builds = _Builds(monkeypatch)
    cache.page(snap, effective_schema({}, snap.declared_schema()), top="jobs", **DEFAULT)
    assert builds.calls == []


def test_a_servers_startup_warm_up_sorts_a_store_app_by_its_settings(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient
    from vmn_exp.core.app_settings_store import write_settings
    from vmn_exp.storage.local import LocalSnapshotStorage
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    storage.save("app", "1.0.0-dev.a", {"verstr": "1.0.0-dev.a",
                                        "timestamp": "2026-01-01T00:00:00Z"}, {})
    write_settings(storage, "app", "metrics: {loss: {goal: min}}\n")
    built = []
    static_of = LeaderboardCache._static_of
    monkeypatch.setattr(LeaderboardCache, "_static_of",
                        lambda s, base, key, *a: built.append(key) or static_of(s, base, key, *a))
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("st", f"file://{tmp_path / 'store'}")
    app = create_app(manager, background_refresh=True)
    try:
        with TestClient(app):
            assert app.state.warmed.wait(30)
    finally:
        app.state.refresher.stop()
    assert json.dumps({"loss": {"goal": "min"}}) in built


class _Index:
    pass


def test_a_refreshed_snapshot_and_its_views_belong_to_the_app_its_index_serves():
    from vmn_exp.ui.snapshot_owners import SnapshotOwners

    owners, index, snap = SnapshotOwners(), _Index(), _fleet().snapshot()
    owners.refreshed(index, snap)
    assert owners.of(snap) is None
    owners.serves(index, ("ws", "app"))
    owners.refreshed(index, snap)
    assert owners.of(snap) == ("ws", "app")
    assert owners.of(snap.summarized(SCHEMA)) == ("ws", "app")
    assert owners.of(object()) is None and owners.of([]) is None
