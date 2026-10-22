"""``vmn-exp backfill-children <app> [--dry-run]``: write the child markers
a store's runs predate (or lost), from one pass over the index."""
import pytest
from exp_helpers import _bootstrap, _exp, _storage

from vmn_exp.cli import backfill_children
from vmn_exp.core.writer import create_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "my_app"
CODE = "0.0.1-dev.abc.def"


def _run(storage, parent=None):
    return create_run(storage, APP, CODE, {"timestamp": "2026-01-01T00:00:00Z"}, {},
                      parent=parent)


@pytest.fixture
def tree(tmp_path):
    """An outer run with three children and a nested outer, markers lost."""
    storage = LocalSnapshotStorage(str(tmp_path / "root"), area="runs")
    outer = _run(storage)
    kids = [_run(storage, parent=outer) for _ in range(3)]
    grandkid = _run(storage, parent=kids[0])
    _run(storage)
    for kid in kids:
        storage.unmark_child(APP, outer, kid)
    storage.unmark_child(APP, kids[0], grandkid)
    storage.mark_child(APP, outer, kids[2])  # one survived
    return storage, outer, kids, grandkid


def test_backfill_writes_the_missing_markers(tree):
    storage, outer, kids, grandkid = tree

    counts = backfill_children.backfill_app(storage, APP)

    assert counts == {"wrote": 3, "present": 1, "failed": 0}
    assert storage.list_children(APP, outer) == sorted(kids)
    assert storage.list_children(APP, kids[0]) == [grandkid]


def test_backfill_is_idempotent(tree):
    storage = tree[0]
    backfill_children.backfill_app(storage, APP)

    assert backfill_children.backfill_app(storage, APP) == {
        "wrote": 0, "present": 4, "failed": 0}


def test_dry_run_writes_nothing(tree):
    storage, outer, kids, _ = tree

    counts = backfill_children.backfill_app(storage, APP, dry_run=True)

    assert counts == {"wrote": 3, "present": 1, "failed": 0}
    assert storage.list_children(APP, outer) == [kids[2]]


def test_a_child_whose_parent_is_gone_is_left_alone(tree):
    storage, outer, kids, grandkid = tree
    storage.delete(APP, outer)

    counts = backfill_children.backfill_app(storage, APP)

    assert counts == {"wrote": 1, "present": 0, "failed": 0}
    assert storage.list_children(APP, kids[0]) == [grandkid]


def test_a_failing_marker_is_counted_and_the_rest_written(tree, monkeypatch):
    storage, outer, kids, grandkid = tree
    real = storage.mark_child

    def flaky(app, parent, child):
        if child == kids[0]:
            raise OSError("nope")
        return real(app, parent, child)

    monkeypatch.setattr(storage, "mark_child", flaky)

    counts = backfill_children.backfill_app(storage, APP)

    assert counts == {"wrote": 2, "present": 1, "failed": 1}


def test_cli_backfill_prints_its_counts(app_layout, capfd):
    _bootstrap(app_layout)
    app = app_layout.app_name
    assert _exp(app) == 0
    storage = _storage(app_layout)
    outer = storage.list_snapshots(app)[-1]["verstr"]
    assert _exp(app, extra_args=["--parent", outer]) == 0
    inner = storage.list_snapshots(app)[-1]["verstr"]
    storage.unmark_child(app, outer, inner)

    capfd.readouterr()
    assert _exp(app, action="backfill-children", extra_args=["--dry-run"]) == 0
    assert capfd.readouterr().out.splitlines()[-1] == "wrote 1, present 0 (dry run: nothing written)"
    assert storage.list_children(app, outer) == []

    assert _exp(app, action="backfill-children") == 0
    assert capfd.readouterr().out.splitlines()[-1] == "wrote 1, present 0"
    assert storage.list_children(app, outer) == [inner]

    assert _exp(app, action="backfill-children") == 0
    assert capfd.readouterr().out.splitlines()[-1] == "wrote 0, present 1"


def test_backfill_children_is_a_writing_action():
    from vmn_exp.cli.experiment import READ_ONLY_ACTIONS
    from vmn_exp.cli.plugin import EXPERIMENT_ACTIONS

    assert "backfill-children" in EXPERIMENT_ACTIONS
    assert "backfill-children" not in READ_ONLY_ACTIONS


def test_backfill_reads_metadata_only_never_the_index(tree, monkeypatch):
    """A cold index load reads every run's state and logs (tens of minutes
    at 50k runs); a parent link is in ``metadata.yml`` alone."""
    from vmn_exp.core import index

    def no_index(*a, **k):
        raise AssertionError("backfill must not load the index")

    monkeypatch.setattr(index, "indexed_snapshot", no_index)
    monkeypatch.setattr(index, "shared_index", no_index)
    storage = tree[0]
    monkeypatch.setattr(storage, "load_file", lambda app, v, name: pytest.fail(name)
                        if name != "metadata.yml" else type(storage).load_file(storage, app, v, name))

    assert backfill_children.backfill_app(storage, APP)["wrote"] == 3


def test_backfill_reports_progress_on_stderr(tree, monkeypatch, capsys):
    monkeypatch.setattr(backfill_children, "PROGRESS_EVERY", 2)

    backfill_children.backfill_app(tree[0], APP)

    err = capsys.readouterr().err
    assert "read 2/6 runs" in err and "read 6/6 runs" in err
