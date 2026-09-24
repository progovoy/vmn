"""The experiment query language over HTTP: ``GET .../experiments?q=...``.

The endpoint applies ``q`` exactly where ``status`` is applied — after status
derivation, before ordering and pagination — so ``total`` counts matching rows.
A query that will not compile is the user's typo, not a server fault: it answers
400 with the compiler's message (offset included) instead of an empty list.
"""
import json
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

API = "/api/v1/workspaces/main/apps"


def _exp_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


def _append_log(app_layout, verstr, entry, writer="w0"):
    path = os.path.join(_exp_dir(app_layout, verstr), f"log.{writer}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _write_experiment(
    app_layout, verstr, run_state=None, metrics=None, params=None, note=None
):
    """An experiment dir as ``vmn exp`` would leave it on disk."""
    path = _exp_dir(app_layout, verstr)
    meta = {
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": f"2026-09-21T12:00:{int(verstr[-1]):02d}",
        "note": note if note is not None else f"note-{verstr}",
        "branch": "master",
        "base_version": "0.0.1",
    }
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f, sort_keys=True)
    if run_state is not None:
        with open(os.path.join(path, "run_state.yml"), "w") as f:
            yaml.dump(run_state, f, sort_keys=False)
    if params is not None:
        _append_log(
            app_layout,
            verstr,
            {"timestamp": "2026-09-21T12:00:00Z", "type": "create", "params": params},
        )
    if metrics is not None:
        _append_log(
            app_layout,
            verstr,
            {
                "timestamp": "2026-09-21T12:00:01Z",
                "type": "metrics",
                "values": metrics,
            },
        )
    return path


def _finished_state(exit_code):
    return {
        "state": "finished",
        "command": ["python", "train.py"],
        "pid": 4242,
        "host": "somebox",
        "started_at": "2026-09-21T12:00:00Z",
        "heartbeat": "2026-09-21T12:05:00Z",
        "heartbeat_interval_sec": 30,
        "exit_code": exit_code,
        "finished_at": "2026-09-21T12:05:00Z",
        "duration_sec": 300.0,
    }


def _client(app_layout, use_index=True):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    # A data dir per client, so a test can hold both read paths open at once.
    manager = WorkspaceManager(
        os.path.join(app_layout.base_dir, f"ui_data_{use_index}")
    )
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager, use_index=use_index))


def _seed(app_layout):
    """Five runs spanning statuses, metrics and params."""
    _write_experiment(
        app_layout, "0.0.1", metrics={"loss": 0.9}, params={"model": "xgb"}
    )
    _write_experiment(
        app_layout,
        "0.0.2",
        run_state=_finished_state(0),
        metrics={"loss": 0.1},
        params={"model": "xgb", "cache": True},
    )
    _write_experiment(
        app_layout,
        "0.0.3",
        run_state=_finished_state(0),
        metrics={"loss": 0.4},
        params={"model": "linear"},
    )
    _write_experiment(
        app_layout,
        "0.0.4",
        run_state=_finished_state(2),
        metrics={"loss": 0.2},
        params={"model": "linear"},
    )
    _write_experiment(app_layout, "0.0.5", metrics={"loss": 2.0}, params={})


def _url(app_layout):
    return f"{API}/{app_layout.app_name}/experiments"


def _verstrs(response):
    return sorted(r["verstr"] for r in response.json())


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_metric_comparison_narrows_the_rows(app_layout):
    _seed(app_layout)
    client = _client(app_layout)

    resp = client.get(_url(app_layout), params={"q": "metrics.loss < 0.5"})
    assert resp.status_code == 200
    assert _verstrs(resp) == ["0.0.2", "0.0.3", "0.0.4"]


def test_status_in_list_query(app_layout):
    _seed(app_layout)
    client = _client(app_layout)

    resp = client.get(
        _url(app_layout), params={"q": 'status in ("failed", "created")'}
    )
    assert resp.status_code == 200
    assert _verstrs(resp) == ["0.0.1", "0.0.4", "0.0.5"]


def test_params_string_match(app_layout):
    """``params.<name>`` reads the run's values verbatim, so strings match."""
    _seed(app_layout)
    client = _client(app_layout)

    resp = client.get(_url(app_layout), params={"q": 'params.model = "xgb"'})
    assert resp.status_code == 200
    assert _verstrs(resp) == ["0.0.1", "0.0.2"]

    resp = client.get(_url(app_layout), params={"q": "params.cache = true"})
    assert _verstrs(resp) == ["0.0.2"]


def test_query_and_status_compose_as_and(app_layout):
    _seed(app_layout)
    client = _client(app_layout)

    # Each filter alone keeps rows the other drops, so only an AND gives 0.0.3.
    assert _verstrs(client.get(_url(app_layout), params={"status": "succeeded"})) == [
        "0.0.2",
        "0.0.3",
    ]
    resp = client.get(_url(app_layout), params={"q": "metrics.loss > 0.3"})
    assert _verstrs(resp) == ["0.0.1", "0.0.3", "0.0.5"]

    resp = client.get(
        _url(app_layout),
        params={"q": "metrics.loss > 0.3", "status": "succeeded"},
    )
    assert resp.status_code == 200
    assert _verstrs(resp) == ["0.0.3"]


@pytest.mark.parametrize("use_index", [True, False])
def test_query_applies_before_pagination(app_layout, use_index):
    """``total`` counts matching rows, so paging walks the matching set."""
    _seed(app_layout)
    client = _client(app_layout, use_index=use_index)
    params = {"q": "metrics.loss < 0.5", "limit": 1}

    first = client.get(_url(app_layout), params=params).json()
    assert first["total"] == 3
    assert [r["verstr"] for r in first["rows"]] == ["0.0.2"]

    second = client.get(_url(app_layout), params={**params, "offset": 2}).json()
    assert second["total"] == 3
    assert [r["verstr"] for r in second["rows"]] == ["0.0.4"]


def test_no_query_returns_every_row(app_layout):
    _seed(app_layout)
    client = _client(app_layout)

    assert len(client.get(_url(app_layout)).json()) == 5
    assert len(client.get(_url(app_layout), params={"q": ""}).json()) == 5


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["metrics.loss <", "bogus_field = 1", "status = ", "status = 'a' and"],
)
def test_invalid_query_answers_400_with_an_offset(app_layout, query):
    _seed(app_layout)
    resp = _client(app_layout).get(_url(app_layout), params={"q": query})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "at offset" in detail, detail


def test_invalid_query_is_not_an_empty_200(app_layout):
    _seed(app_layout)
    resp = _client(app_layout).get(_url(app_layout), params={"q": "loss ~ 3"})

    assert resp.status_code == 400
    assert "at offset" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Parity across the read paths
# ---------------------------------------------------------------------------


def test_indexed_and_direct_paths_agree(app_layout):
    _seed(app_layout)
    query = 'metrics.loss < 0.5 and params.model = "linear"'

    indexed = _client(app_layout, use_index=True).get(
        _url(app_layout), params={"q": query}
    )
    direct = _client(app_layout, use_index=False).get(
        _url(app_layout), params={"q": query}
    )
    assert _verstrs(indexed) == _verstrs(direct) == ["0.0.3", "0.0.4"]


def _storage_page(app_layout, tmp_path, query):
    """The S3 workspace list pipeline: index snapshot, then the leaderboard memo."""
    from helpers import _storage

    from version_stamp.ui.index import app_snapshot
    from version_stamp.ui.leaderboard_cache import LeaderboardCache

    snapshot = app_snapshot(
        _storage(app_layout), app_layout.app_name, str(tmp_path / "idx.sqlite")
    )
    return LeaderboardCache().page(snapshot, {}, query=query)


def test_storage_backed_reader_filters_too(app_layout, tmp_path):
    """The S3 path shares the filter — it takes ``query`` like the others."""
    _seed(app_layout)
    rows = _storage_page(app_layout, tmp_path, "metrics.loss < 0.5")
    assert sorted(r["verstr"] for r in rows) == ["0.0.2", "0.0.3", "0.0.4"]


def test_storage_backed_reader_raises_on_a_bad_query(app_layout, tmp_path):
    from version_stamp.core.experiment_query import QueryError

    _seed(app_layout)
    with pytest.raises(QueryError):
        _storage_page(app_layout, tmp_path, "metrics.loss <")
