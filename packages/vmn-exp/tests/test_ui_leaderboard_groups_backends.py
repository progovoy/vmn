"""Plan 22 K3: the grouped list (``?group=``/``?agg=``) gives the same answer
whichever cache holds the app's index: in memory (``--no-index``), the
SQLite file of a git or a store workspace (also after a restart), or
Postgres (``db: postgresql://``: the elected leader and a follower that reads
the rows back; skipped without docker/psycopg). Every backend serves lists
through the one in-memory ``LeaderboardCache``; this pins that the records
they persist and reload carry everything grouping reads, cold and after a
new generation."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from vmn_exp.ui.leaderboard_group_fields import NONE

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
CODE = "0.0.1-dev.abc1234.c0de000"


def v(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


# n, state, metadata links, params, tags, losses (the last one is the fold's)
RUNS = [
    (1, "ok", {}, {"lr": 0.1}, {"team": "a"}, [0.5]),
    (2, "ok", {"parent": 1, "code_verstr": CODE}, {"lr": 0.1}, {"team": "a"}, [9.0]),
    (3, "failed", {"parent": 1, "code_verstr": CODE}, {"lr": 0.01}, {}, [1.0, float("nan")]),
    (4, "ok", {"forked_from": 2, "branch": "dev"}, {"lr": 0.01}, {"team": "b"}, [3.0]),
    (5, "ok", {"rerun_of": 2, "code_verstr": CODE}, {"lr": 0.1}, {}, [8.0]),
    (6, "ok", {"parent": 4, "rerun_of": 99}, {}, {"team": "b"}, []),
    (7, "ok", {"parent": 1, "branch": "dev"}, {"lr": 0.1}, {}, [2.0]),
]

QUERIES = [
    {"group": "parent"},
    {"group": "parent", "agg": "best", "sort": "metrics.loss", "order": "asc"},
    {"group": "parent", "agg": "median", "rows_per_group": 1},
    {"group": "parent", "group_key": v(1), "offset": 1, "limit": 1},
    {"group": "parent", "q": "params.lr = 0.1"},
    {"group": "parent", "status": "succeeded"},
    {"group": "forked_from"},
    {"group": "rerun_of", "agg": "max"},
    {"group": "code_verstr", "agg": "min"},
    {"group": "branch"},
    {"group": "status"},
    {"group": "params.lr", "sort": "metrics.loss", "order": "desc"},
    {"group": "tags.team", "limit": 1, "offset": 1},
    {"group": "parent", "sort": "c:total", "order": "desc"},
    {"group": "params.lr", "sort": "c:failed"},
    {"group": "code_verstr", "sort": "c:done", "order": "asc", "status": "succeeded"},
]


def _meta(n, links):
    meta = {"format_version": 1, "verstr": v(n), "timestamp": f"2026-01-01T00:00:{n:02d}Z",
            "branch": links.get("branch", "main")}
    for link in ("parent", "rerun_of"):
        if link in links:
            meta[link] = v(links[link])
    if "forked_from" in links:
        meta["forked_from"] = {"verstr": v(links["forked_from"]), "step": 1}
    if "code_verstr" in links:
        meta["code_verstr"] = links["code_verstr"]
    return meta


def _log(params, tags, losses):
    entries = [{"timestamp": "t", "type": "create", "params": params, "tags": tags},
               {"timestamp": "t", "type": "define_metric", "name": "loss", "goal": "min"}]
    entries += [{"timestamp": "t", "type": "metrics", "step": i, "values": {"loss": x}}
                for i, x in enumerate(losses)]
    return "".join(json.dumps(e) + "\n" for e in entries)


def _write_run(store, n, state, links, params, tags, losses):
    folder = os.path.join(store, "runs", APP, v(n))
    os.makedirs(os.path.join(folder, "log"))
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.write(_log(params, tags, losses))
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        f.write(f"state: finished\nexit_code: {0 if state == 'ok' else 1}\n")
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(_meta(n, links), f)


def _make_repo(root):
    (root / ".git").mkdir(parents=True)
    store = str(root / ".vmn" / "store")
    os.makedirs(store)
    with open(os.path.join(store, "store.yml"), "w") as f:
        yaml.dump({"layout": 2, "created_at": "2026-01-01T00:00:00Z"}, f)
    for spec in RUNS:
        _write_run(store, *spec)
    return str(root), store


@pytest.fixture
def repo(tmp_path):
    return _make_repo(tmp_path / "repo")


def _client(tmp_path, repo, backend, dsn=None, replica=""):
    """A server over *repo* whose index cache is *backend*; servers of one
    *replica* name share their data dir (a restart)."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root, store = repo
    data = tmp_path / f"data-{os.path.basename(root)}-{backend}{replica}"
    manager = WorkspaceManager(str(data))
    if manager.get("ws") is None and backend.startswith("git"):
        manager.attach_path("ws", root)
    elif manager.get("ws") is None:
        manager.add_store("ws", f"file://{store}")
    app = create_app(manager, use_index=backend != "git-memory",
                     cache_dsn=dsn if backend == "store-postgres" else None)
    return TestClient(app)


def _warm(client):
    assert client.get(BASE).status_code == 200


def _without_clock(value):
    """*value* without ``stale_sec`` (seconds since the run's last write,
    measured at request time, so it differs between any two requests)."""
    if isinstance(value, dict):
        return {k: _without_clock(x) for k, x in value.items() if k != "stale_sec"}
    if isinstance(value, list):
        return [_without_clock(x) for x in value]
    return value


def _answers(client):
    answers = []
    for params in QUERIES:
        response = client.get(BASE, params=params)
        assert response.status_code == 200, (params, response.text)
        answers.append(_without_clock(response.json()))
    return answers


def _change(store):
    """A new generation: run 8 joins sweep 4, run 7 gets a second loss."""
    _write_run(store, 8, "failed", {"parent": 4}, {"lr": 0.01}, {"team": "a"}, [0.25])
    with open(os.path.join(store, "runs", APP, v(7), "log", "w2.jsonl"), "w") as f:
        f.write(json.dumps({"timestamp": "t", "type": "metrics", "step": 9,
                            "values": {"loss": 7.0}}) + "\n")


def _before_and_after(client, store):
    """The answers, then the answers once the store moved on (the cache's
    delta path, not a cold build)."""
    before = _answers(client)
    _change(store)
    return before, _answers(client)


@pytest.fixture
def reference(tmp_path):
    """The in-memory index's answers, over a copy of the same records."""
    copy = _make_repo(tmp_path / "reference")
    return _before_and_after(_client(tmp_path, copy, "git-memory"), copy[1])


def test_the_reference_groups_every_run_and_follows_changes(tmp_path, repo, reference):
    before, after = reference
    assert [g["key"] for g in before[0]["groups"]] == [v(1), v(4), NONE]
    assert (before[0]["total_rows"], after[0]["total_rows"]) == (len(RUNS), len(RUNS) + 1)
    _change(repo[1])
    assert after == _answers(_client(tmp_path, repo, "git-memory"))


@pytest.mark.parametrize("backend", ["git-sqlite", "store-sqlite"])
def test_sqlite_caches_group_like_the_in_memory_index(tmp_path, repo, reference, backend):
    assert _before_and_after(_client(tmp_path, repo, backend), repo[1]) == reference


@pytest.mark.parametrize("backend", ["git-sqlite", "store-sqlite"])
def test_a_restart_groups_from_the_sqlite_file_like_the_in_memory_index(
        tmp_path, repo, reference, backend, monkeypatch):
    from vmn_exp.core import index

    _warm(_client(tmp_path, repo, backend))
    monkeypatch.setattr(index, "_SHARED", {})  # a new process: no warm index
    restarted = _client(tmp_path, repo, backend)
    assert _before_and_after(restarted, repo[1]) == reference


def test_a_postgres_follower_groups_like_the_in_memory_index(
        tmp_path, repo, reference, pg_dsn):
    leader = _client(tmp_path, repo, "store-postgres", pg_dsn, replica="-leader")
    _warm(leader)
    follower = _client(tmp_path, repo, "store-postgres", pg_dsn, replica="-follower")
    before = _answers(follower)
    _change(repo[1])
    _warm(leader)  # the elected leader saves the new generation
    assert (before, _answers(follower)) == reference


def test_the_postgres_leader_groups_like_the_in_memory_index(
        tmp_path, repo, reference, pg_dsn):
    client = _client(tmp_path, repo, "store-postgres", pg_dsn)
    assert _before_and_after(client, repo[1]) == reference


@pytest.mark.parametrize("backend", ["git-memory", "store-sqlite"])
def test_an_unknown_group_field_is_a_400_on_every_backend(tmp_path, repo, backend):
    response = _client(tmp_path, repo, backend).get(BASE, params={"group": "nope"})
    assert response.status_code == 400
