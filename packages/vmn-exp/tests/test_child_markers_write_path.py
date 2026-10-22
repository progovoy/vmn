"""Every run created with a parent marks itself in the parent's record —
CLI create/run, sweeps, reruns, the SDK and imports all claim through
``core.writer`` — and a pruned child drops its marker. Best-effort: a marker
that cannot be written never fails the child."""
import pytest
from exp_helpers import _bootstrap, _exp, _storage
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.core.writer import claim_record, create_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


@pytest.fixture
def local(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "root"), area="runs")


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture(params=["local", "s3"])
def store(request):
    return request.getfixturevalue(request.param)


def test_a_child_marks_itself_in_its_parent(store):
    outer = _run(store)
    kids = [_run(store, parent=outer) for _ in range(3)]

    assert store.list_children(APP, outer) == sorted(kids)
    assert all(store.list_children(APP, kid) == [] for kid in kids)


def test_a_run_without_a_parent_marks_nothing(store):
    outer = _run(store)
    _run(store)

    assert store.list_children(APP, outer) == []


def test_a_claimed_record_with_a_parent_marks_it(store):
    outer = _run(store)
    meta = {"verstr": "imported.1", "timestamp": "2026-01-01T00:00:00Z", "parent": outer}

    assert claim_record(store, APP, "imported.1", meta)

    assert store.list_children(APP, outer) == ["imported.1"]


def test_a_failing_marker_never_fails_the_child(local, monkeypatch):
    outer = _run(local)

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(local, "mark_child", broken)
    kid = _run(local, parent=outer)

    assert local.load_metadata(APP, kid)["parent"] == outer


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def test_cli_create_with_parent_marks_it(app_layout):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)

    assert _storage(app_layout).list_children(app_layout.app_name, outer) == [inner]


def test_pruning_a_child_drops_its_marker(app_layout, capfd):
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)
    other = _create(app_layout, "--parent", outer)

    assert _exp(app_layout.app_name, action="prune", version=inner) == 0

    assert _storage(app_layout).list_children(app_layout.app_name, outer) == [other]


def test_pushing_an_offline_child_marks_its_parent_on_the_remote(tmp_path, s3):
    from push_helpers import APP as PUSH_APP, X, local_root, make_run
    from vmn_exp.core.push_run import NEW, push_run

    local = local_root(tmp_path)
    outer = make_run(local, tmp_path, verstr=X + ".outer")
    kid = make_run(local, tmp_path, verstr=X + ".kid", parent=outer)
    assert push_run(local, s3, PUSH_APP, outer).status == NEW

    assert push_run(local, s3, PUSH_APP, kid).status == NEW

    assert s3.list_children(PUSH_APP, outer) == [kid]
