"""Registry lineage over HTTP (plan 06): the run lineage route's used-version
links and ``datasets``, ``GET .../models/{name}/versions/{n}/lineage`` and the
models list's ``kind``."""
import pytest
from helpers import _storage
from test_ui_lineage_api import _get, _write_run, client  # noqa: F401 (fixture)

from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.registry.log import record_use
from vmn_exp.registry.names import registry_uri
from vmn_exp.registry.store import ensure_model, register_version

pytest.importorskip("fastapi")

MODELS = "/api/v1/workspaces/main/models"
TS = "2026-09-27T10:00:00Z"


def _clf(app_layout):
    storage = _storage(app_layout)
    ensure_model(storage, "clf")
    register_version(storage, "clf", {"app": app_layout.app_name, "verstr": "0.0.1-exp.train"},
                     artifact_path="model.pkl")
    return storage


def _reference_dataset(storage, name="ds"):
    ensure_model(storage, name, kind="dataset")
    register_version(storage, name, uri="s3://b/train.csv", digest="sha256:" + "f" * 64)


def test_run_lineage_links_carry_the_used_version(client, app_layout):  # noqa: F811
    _clf(app_layout)
    link = _get(client, app_layout, "0.0.1-exp.eval").json()["upstream"][0]["links"][0]
    assert (link["model"], link["version"], link["kind"]) == ("clf", 1, "model")


def test_run_lineage_lists_reference_datasets(client, app_layout):  # noqa: F811
    _reference_dataset(_storage(app_layout))
    _write_run(app_layout, "0.0.1-exp.fit", [
        {"type": "input", "ts": TS, "name": "ds@1", "uri": registry_uri("ds", 1),
         "digest": "sha256:" + "f" * 64, "kind": "dataset"},
    ], 4)
    body = _get(client, app_layout, "0.0.1-exp.fit").json()
    assert body["upstream"] == []
    assert [(d["model"], d["version"], d["found"]) for d in body["datasets"]] == [("ds", 1, True)]


def test_version_lineage_endpoint(client, app_layout):  # noqa: F811
    storage = _clf(app_layout)
    record_use(storage, "clf", 1, app_layout.app_name, "0.0.1-exp.eval")
    record_use(storage, "clf", 1, app_layout.app_name, "0.0.1-exp.gone")

    resp = client.get(f"{MODELS}/clf/versions/1/lineage")
    assert resp.status_code == 200
    body = resp.json()
    assert (body["model"], body["version"], body["kind"], body["status"]) == (
        "clf", 1, "model", "active",
    )
    assert (body["producer"]["verstr"], body["producer"]["status"]) == ("0.0.1-exp.train", "created")
    assert [(n["verstr"], n["found"]) for n in body["consumers"]] == [
        ("0.0.1-exp.eval", True), ("0.0.1-exp.gone", False),
    ]


def test_version_lineage_unknown_version_is_404_bad_name_is_400(client, app_layout):  # noqa: F811
    _clf(app_layout)
    assert client.get(f"{MODELS}/clf/versions/7/lineage").status_code == 404
    assert client.get(f"{MODELS}/bad-name/versions/1/lineage").status_code == 400


def test_models_list_includes_kind_and_filters(client, app_layout):  # noqa: F811
    _reference_dataset(_clf(app_layout))
    rows = client.get(MODELS).json()["models"]
    assert sorted((r["name"], r["kind"]) for r in rows) == [("clf", "model"), ("ds", "dataset")]
    only = client.get(MODELS, params={"kind": "dataset"}).json()["models"]
    assert [r["name"] for r in only] == ["ds"]
    assert client.get(MODELS, params={"kind": "nope"}).status_code == 400
    assert client.get(f"{MODELS}/ds").json()["kind"] == "dataset"


def test_uri_input_of_an_unregistered_artifact_has_plain_links(client, app_layout):  # noqa: F811
    _write_run(app_layout, "0.0.1-exp.raw", [
        {"type": "input", "ts": TS, "name": "m", "kind": None, "digest": None,
         "uri": artifact_ref_uri(app_layout.app_name, "0.0.1-exp.train", "model.pkl")},
    ], 5)
    link = _get(client, app_layout, "0.0.1-exp.raw").json()["upstream"][0]["links"][0]
    assert "model" not in link
