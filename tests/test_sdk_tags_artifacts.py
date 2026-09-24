"""SDK run names, tags, archiving and the artifact helpers.

``start_run(name=..., tags=...)``, ``run.set_tag``/``set_tags`` (also on a
finished run), ``log_dict``/``log_text``/``log_figure``/``log_artifacts``, and
``version_stamp.exp.manage.archive_run`` which ``list_runs`` honours.
"""
import json

import pytest
import yaml
from helpers import _bootstrap, _storage

from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.core.experiment_log import experiment_row
from version_stamp.exp import manage, reader, start_run
from version_stamp.exp.run import Run

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "experiments"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


@pytest.fixture
def run(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    yield run
    run.finish()


def _row(storage):
    meta = storage.load_metadata(APP, VERSTR)
    return experiment_row(1, meta, storage.load_merged_log(APP, VERSTR))


def _artifact(storage, name):
    with open(storage.artifact_local_path(APP, VERSTR, name), "rb") as f:
        return f.read()


# -- tags ------------------------------------------------------------------------


def test_set_tag_and_set_tags_fold_into_the_row(run, storage):
    run.set_tag("stage", "dev")
    run.set_tags({"stage": "prod", "owner": "ann"})
    run.finish()
    assert _row(storage)["tags"] == {"stage": "prod", "owner": "ann"}


def test_remove_tag(run, storage):
    run.set_tags({"a": "1", "b": "2"})
    run.remove_tag("a")
    run.finish()
    assert _row(storage)["tags"] == {"b": "2"}


def test_tags_can_be_set_on_a_finished_run(run, storage):
    run.finish()
    run.set_tag("verdict", "keep")
    assert _row(storage)["tags"] == {"verdict": "keep"}


# -- artifact helpers ---------------------------------------------------------------


def test_log_dict_writes_json_or_yaml_by_extension(run, storage):
    run.log_dict({"lr": 0.1}, "conf/params.json")
    run.log_dict({"lr": 0.2}, "conf/params.yaml")
    run.finish()
    assert json.loads(_artifact(storage, "conf/params.json")) == {"lr": 0.1}
    assert yaml.safe_load(_artifact(storage, "conf/params.yaml")) == {"lr": 0.2}
    logged = [e["path"] for e in storage.load_merged_log(APP, VERSTR) if e["type"] == "artifact"]
    assert logged == ["conf/params.json", "conf/params.yaml"]


def test_log_dict_rejects_an_unknown_extension(run):
    with pytest.raises(ValueError):
        run.log_dict({"a": 1}, "params.toml")


def test_log_text(run, storage):
    run.log_text("hello\n", "notes/readme.txt")
    run.finish()
    assert _artifact(storage, "notes/readme.txt") == b"hello\n"


class _Figure:
    def savefig(self, path, **kwargs):
        with open(path, "wb") as f:
            f.write(b"PNG" + repr(sorted(kwargs)).encode())


def test_log_figure_saves_through_savefig(run, storage):
    run.log_figure(_Figure(), "plots/loss.png")
    run.finish()
    assert _artifact(storage, "plots/loss.png").startswith(b"PNG")


def test_log_artifacts_uploads_a_tree_with_nested_names(run, storage, tmp_path):
    tree = tmp_path / "out"
    (tree / "sub" / "deep").mkdir(parents=True)
    (tree / "a.txt").write_text("a")
    (tree / "sub" / "deep" / "c.txt").write_text("c")

    run.log_artifacts(str(tree), prefix="model")
    run.finish()

    names = [a["name"] for a in storage.list_artifacts(APP, VERSTR)]
    assert names == ["model/a.txt", "model/sub/deep/c.txt"]
    assert _artifact(storage, "model/sub/deep/c.txt") == b"c"


def test_log_artifacts_without_prefix(run, storage, tmp_path):
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "x.bin").write_bytes(b"x")
    run.log_artifacts(str(tmp_path / "t"))
    run.finish()
    assert [a["name"] for a in storage.list_artifacts(APP, VERSTR)] == ["x.bin"]


def test_log_artifact_path_names_are_validated(run, tmp_path):
    with pytest.raises(ValueError):
        run.log_text("x", "../escape.txt")


# -- start_run(name, tags), archive and list_runs (a real checkout) --------------------


def test_named_tagged_run_and_archiving(app_layout):
    _bootstrap(app_layout)
    app = app_layout.app_name

    with start_run(app, name="lr-sweep-1", tags={"team": "nlp"}) as named:
        assert named.name == "lr-sweep-1"
    with start_run(app) as other:
        pass

    meta = _storage(app_layout).load_metadata(app, named.id)
    assert meta["name"] == "lr-sweep-1"
    rows = {r["verstr"]: r for r in reader.list_runs(app)}
    assert rows[named.id]["name"] == "lr-sweep-1"
    assert rows[named.id]["tags"] == {"team": "nlp"}

    manage.archive_run(app, other.id)
    assert [r["verstr"] for r in reader.list_runs(app)] == [named.id]
    shown = reader.list_runs(app, include_archived=True, query="archived = true")
    assert [r["verstr"] for r in shown] == [other.id]

    manage.unarchive_run(app, other.id)
    assert len(reader.list_runs(app)) == 2


def test_manage_set_tags_on_a_stored_run(app_layout):
    _bootstrap(app_layout)
    app = app_layout.app_name
    with start_run(app) as run:
        pass

    manage.set_tags(app, run.id, {"k": "v", "x": "1"}, remove=["x"])

    assert reader.get_run(app, run.id)["tags"] == {"k": "v"}
