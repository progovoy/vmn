"""One read path for the ui: shared sort/tree helpers in core, one leaderboard
pipeline, cached detail reads, streamed S3 artifacts, validated query params."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core import experiment_index
from version_stamp.core.experiment_log import sort_by_metric
from version_stamp.core.experiment_tree import subtree_status

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _ts(i):
    return f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _row(i, loss=None, ts=True):
    metrics = {} if loss is None else {"loss": loss}
    return {"idx": i, "verstr": f"v{i}", "timestamp": _ts(i) if ts else None, "metrics": metrics}


# ---- core sort -------------------------------------------------------------


def test_sort_direction_can_be_forced_either_way_with_missing_last():
    rows = [_row(0, 0.3), _row(1), _row(2, 0.1), _row(3, 0.2)]
    schema = {"loss": {"goal": "max"}}

    down = sort_by_metric(rows, schema, sort="loss", descending=True)
    up = sort_by_metric(rows, schema, sort="loss", descending=False)

    assert [r["metrics"].get("loss") for r in down] == [0.3, 0.2, 0.1, None]
    assert [r["metrics"].get("loss") for r in up] == [0.1, 0.2, 0.3, None]


def test_timestamp_sort_is_newest_first_by_default_and_undated_last():
    rows = [_row(0), _row(1, ts=False), _row(2), _row(3)]

    newest = sort_by_metric(rows, {}, sort="timestamp")
    oldest = sort_by_metric(rows, {}, sort="timestamp", descending=False)

    assert [r["idx"] for r in newest] == [3, 2, 0, 1]
    assert [r["idx"] for r in oldest] == [0, 2, 3, 1]


def test_forced_direction_without_a_metric_reverses_storage_order():
    rows = [_row(i) for i in range(3)]
    assert [r["idx"] for r in sort_by_metric(rows, {}, descending=True)] == [2, 1, 0]
    assert [r["idx"] for r in sort_by_metric(rows, {})] == [0, 1, 2]


# ---- core tree -------------------------------------------------------------


def test_subtree_status_reads_each_subtree_run_once_and_knows_its_depth():
    parent_of = {"root": None, "outer": "root", "a": "outer", "b": "outer", "x": None}
    states = {
        "outer": {"state": "finished", "exit_code": 0},
        "a": {"state": "finished", "exit_code": 0},
        "b": {"state": "finished", "exit_code": 2},
    }
    reads = []

    def read(verstr):
        reads.append(verstr)
        return states.get(verstr)

    state, tree = subtree_status("outer", parent_of, read)

    assert state == states["outer"]
    assert sorted(reads) == ["a", "b", "outer"]
    assert sorted(tree["children"]) == ["a", "b"]
    assert tree["kind"] == "outer"
    assert tree["depth"] == 1
    assert tree["tree_status"] == "failed"


# ---- one direct read -------------------------------------------------------


def _storage(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    return str(root), get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")


def _runs(storage, n, loss=0.1):
    for i in range(n):
        verstr = f"1.0.0-dev.r{i:04d}"
        storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(i)}, {})
        storage.append_log_entry(
            APP, verstr, "w", {"timestamp": _ts(i), "type": "metrics", "values": {"loss": loss + i}}
        )


def test_direct_rows_reads_through_the_callers_loaders(tmp_path):
    _, storage = _storage(tmp_path)
    _runs(storage, 2)
    logs, states = [], []

    def read_log(st, app, verstr):
        logs.append(verstr)
        return st.load_merged_log(app, verstr)

    rows, run_states = experiment_index.direct_rows(
        storage, APP, read_log=read_log, read_run_state=None
    )

    assert [r["metrics"]["loss"] for r in rows] == [0.1, 1.1]
    assert len(logs) == 2
    assert run_states == {} and states == []


def test_shared_index_is_keyed_by_an_explicit_cache_path(tmp_path):
    _, storage = _storage(tmp_path)
    _runs(storage, 1)
    db = str(tmp_path / "server.sqlite")

    first = experiment_index.shared_index(storage, APP, cache_path=db)
    again = experiment_index.shared_index(storage, APP, cache_path=db)
    rows = experiment_index.indexed_snapshot(storage, APP, cache_path=db).rows

    assert first is again
    assert os.path.isfile(db)
    assert [r["metrics"]["loss"] for r in rows] == [0.1]


def test_one_leaderboard_pipeline_filters_orders_and_pages():
    from version_stamp.ui.readers.experiments import leaderboard

    rows = [_row(0, 0.3), _row(1, 0.1), _row(2, 0.2)]
    page = leaderboard(rows, {}, {}, sort="loss", order="asc", offset=1, limit=1)

    assert page["total"] == 3
    assert [r["metrics"]["loss"] for r in page["rows"]] == [0.2]
    assert page["rows"][0]["status"] == "created"  # status derived in the pipeline


# ---- server ----------------------------------------------------------------


def _client(tmp_path, use_index=True):
    root, storage = _storage(tmp_path)
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", root)
    return TestClient(create_app(manager, use_index=use_index)), storage


@pytest.mark.parametrize("use_index", [True, False])
def test_unchanged_run_detail_and_log_pages_are_not_reparsed(tmp_path, monkeypatch, use_index):
    from version_stamp.ui.readers import experiments as exp_reader

    client, storage = _client(tmp_path, use_index)
    _runs(storage, 1)
    verstr = "1.0.0-dev.r0000"
    reads = []
    real = exp_reader._load_log

    def counted(st, app, v):
        reads.append(v)
        return real(st, app, v)

    monkeypatch.setattr(exp_reader, "_load_log", counted)

    client.get(f"{BASE}/experiments/{verstr}")
    client.get(f"{BASE}/experiments/{verstr}")
    client.get(f"{BASE}/experiments/{verstr}/log?offset=0&limit=5")
    assert reads == [verstr]

    storage.append_log_entry(
        APP, verstr, "w", {"timestamp": _ts(59), "type": "metrics", "values": {"loss": 9.0}}
    )
    later = os.stat(storage._local._snapshot_dir(APP, verstr)).st_mtime + 5
    for name in os.listdir(storage._local._snapshot_dir(APP, verstr)):
        os.utime(os.path.join(storage._local._snapshot_dir(APP, verstr), name), (later, later))

    detail = client.get(f"{BASE}/experiments/{verstr}").json()
    assert detail["metrics"]["loss"] == 9.0
    assert reads == [verstr, verstr]


@pytest.mark.parametrize(
    "route",
    [
        "changelog?v=..%2F..%2Fx",
        "changelog?from=..%2Fx",
        "config?v=..%2F..%2Fx",
        "deps?v=a%2Fb",
        "deps?to=..",
    ],
)
def test_version_query_params_are_validated(tmp_path, route):
    client, _ = _client(tmp_path)
    assert client.get(f"{BASE}/{route}").status_code == 400


def test_a_storage_path_error_is_a_400(tmp_path, monkeypatch):
    from version_stamp.ui.readers import experiments as exp_reader

    client, _ = _client(tmp_path)

    def refuse(*a, **kw):
        raise ValueError("not a record name")

    monkeypatch.setattr(exp_reader, "get_experiment_from_storage", refuse)
    resp = client.get(f"{BASE}/experiments/1.0.0-dev.x")
    assert resp.status_code == 400
    assert "not a record name" in resp.json()["detail"]


@pytest.fixture
def s3_ws(tmp_path):
    moto = pytest.importorskip("moto")
    import boto3

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        from version_stamp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_s3("ws", bucket="vmn-bucket", prefix="exps")
        yield manager


def test_one_s3_storage_per_workspace(s3_ws, monkeypatch):
    from version_stamp.ui import server as server_mod

    built = []
    real = server_mod.get_snapshot_storage

    def counted(*a, **kw):
        built.append(kw.get("bucket"))
        return real(*a, **kw)

    monkeypatch.setattr(server_mod, "get_snapshot_storage", counted)
    client = TestClient(server_mod.create_app(s3_ws))
    for _ in range(3):
        assert client.get(f"{BASE}/experiments?limit=5").status_code == 200
    client.get("/api/v1/workspaces/ws/apps")

    assert built == ["vmn-bucket"]


def test_s3_artifacts_stream_without_a_disk_cache(s3_ws, tmp_path):
    import tempfile

    from version_stamp.cli.snapshot import S3SnapshotStorage
    from version_stamp.ui.server import create_app

    storage = S3SnapshotStorage("vmn-bucket", prefix="exps")
    verstr = "1.0.0-dev.s3run"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(0)}, {})
    model = tmp_path / "model.bin"
    model.write_bytes(b"w" * 70_000)
    storage.save_artifact_file(APP, verstr, str(model))
    cache = os.path.join(tempfile.gettempdir(), "vmn-artifact-cache")
    before = set(os.listdir(cache)) if os.path.isdir(cache) else set()

    got = TestClient(create_app(s3_ws)).get(f"{BASE}/experiments/{verstr}/artifacts/model.bin")

    after = set(os.listdir(cache)) if os.path.isdir(cache) else set()
    assert got.status_code == 200 and got.content == b"w" * 70_000
    assert "attachment" in got.headers.get("content-disposition", "")
    assert after == before
