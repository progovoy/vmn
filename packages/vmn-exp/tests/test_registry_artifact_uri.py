"""A model version's ``artifact_uri``: a relative ``artifact_path`` lives in
its run's record, so it joins the run's location; an absolute one (a URI of
any scheme, or an absolute path) already says where the artifact is and is
kept as is (fgm saw ``s3://…/runs/app/<verstr>/s3://bucket/model.pt``)."""
import json
from types import SimpleNamespace

import pytest

from vmn_exp.registry.store import artifact_uri_of, ensure_model, register_version
from vmn_exp.storage.local import LocalSnapshotStorage

RUN = {"app": "app", "verstr": "1.0.0"}
ABSOLUTE = ["s3://bucket/models/model.pt", "gs://b/m.pt", "file:///data/m.pt", "/data/models/m.pt"]


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def test_a_relative_path_joins_the_runs_location(tmp_path):
    storage = _storage(tmp_path)
    meta = {"run_ref": RUN, "artifact_path": "model/weights.pt"}
    assert artifact_uri_of(storage, meta) == storage.artifact_uri("app", "1.0.0", "model/weights.pt")
    assert artifact_uri_of(storage, meta).endswith("/1.0.0/model/weights.pt")


@pytest.mark.parametrize("path", ABSOLUTE)
def test_an_absolute_path_is_kept_as_is(tmp_path, path):
    assert artifact_uri_of(_storage(tmp_path), {"run_ref": RUN, "artifact_path": path}) == path


def test_no_artifact_or_no_run_has_no_uri(tmp_path):
    storage = _storage(tmp_path)
    assert artifact_uri_of(storage, {"run_ref": RUN}) is None
    assert artifact_uri_of(storage, {"artifact_path": "model.pt"}) is None
    assert artifact_uri_of(storage, None) is None


def _registered(tmp_path, path):
    storage = _storage(tmp_path)
    ensure_model(storage, "clf")
    register_version(storage, "clf", RUN, artifact_path=path)
    return storage


def test_the_ui_detail_keeps_an_absolute_uri(tmp_path):
    from vmn_exp.ui.readers.models import model_detail_response

    detail, _ = model_detail_response(_registered(tmp_path, ABSOLUTE[0]), "clf")
    assert detail["versions"][0]["artifact_uri"] == ABSOLUTE[0]


def test_model_resolve_keeps_an_absolute_uri(tmp_path, capsys):
    from vmn_exp.registry.cli import _cmd_resolve

    storage = _registered(tmp_path, ABSOLUTE[0])
    assert _cmd_resolve(storage, SimpleNamespace(model_name="clf@1", json=True)) == 0
    assert json.loads(capsys.readouterr().out)["artifact_uri"] == ABSOLUTE[0]
