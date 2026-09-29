"""`vmn-exp model` for datasets and usage (plan 06): register --kind dataset
--uri/--digest, list --kind, resolve/show of a dataset, delete warning."""
import json
import logging

from test_cli_model import _invoke, _register_run, _storage

from vmn_exp.registry.log import record_use
from vmn_exp.registry.store import ensure_model, get_version, list_versions, register_version


def _register(tmp_path, **kwargs):
    return _invoke(tmp_path, dict(action="register", model_name="imagenet", **kwargs))


def test_register_kind_dataset_with_uri(tmp_path, capsys):
    rc = _register(tmp_path, kind="dataset", uri="s3://data/imagenet/", digest="sha256:ab")
    assert rc == 0
    storage = _storage(tmp_path)
    meta = get_version(storage, "imagenet", 1)
    assert (meta["uri"], meta["digest"]) == ("s3://data/imagenet/", "sha256:ab")
    assert "run_ref" not in meta
    assert storage.load("vmn-registry", "imagenet")[0]["kind"] == "dataset"
    assert "imagenet version 1" in capsys.readouterr().out


def test_register_local_uri_is_hashed_and_deduped(tmp_path):
    data = tmp_path / "train.csv"
    data.write_text("a,b\n")
    assert _register(tmp_path, kind="dataset", uri=str(data)) == 0
    assert _register(tmp_path, kind="dataset", uri=str(data)) == 0
    storage = _storage(tmp_path)
    assert list_versions(storage, "imagenet") == [1]
    assert get_version(storage, "imagenet", 1)["digest"].startswith("sha256:")


def test_register_kind_dataset_copied_from_run(tmp_path):
    _register_run(_storage(tmp_path), "prep", "1.0.0")
    rc = _register(tmp_path, kind="dataset", version_ref="1.0.0", app="prep", artifact="d.csv")
    assert rc == 0
    meta = get_version(_storage(tmp_path), "imagenet", 1)
    assert (meta["run_ref"], meta["artifact_path"]) == ({"app": "prep", "verstr": "1.0.0"}, "d.csv")


def test_register_needs_exactly_one_of_version_or_uri(tmp_path):
    _register_run(_storage(tmp_path), "prep", "1.0.0")
    assert _register(tmp_path, kind="dataset") == 1
    assert _register(tmp_path, kind="dataset", uri="s3://x/", version_ref="1.0.0", app="prep") == 1


def test_register_uri_needs_kind_dataset(tmp_path):
    assert _register(tmp_path, uri="s3://data/imagenet/") == 1
    assert list_versions(_storage(tmp_path), "imagenet") == []


def test_register_dataset_under_model_name_fails(tmp_path):
    ensure_model(_storage(tmp_path), "imagenet")
    assert _register(tmp_path, kind="dataset", uri="s3://data/imagenet/") == 1


def test_list_kind_filter(tmp_path, capsys):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    ensure_model(storage, "imagenet", kind="dataset")
    capsys.readouterr()
    assert _invoke(tmp_path, dict(action="list", kind="dataset", json=True)) == 0
    assert json.loads(capsys.readouterr().out) == ["imagenet"]
    assert _invoke(tmp_path, dict(action="list", kind="model")) == 0
    assert capsys.readouterr().out.split() == ["resnet"]
    assert _invoke(tmp_path, dict(action="list")) == 0
    assert capsys.readouterr().out.split() == ["imagenet", "resnet"]


def test_resolve_and_show_a_reference_dataset(tmp_path, capsys):
    storage = _storage(tmp_path)
    ensure_model(storage, "imagenet", kind="dataset")
    register_version(storage, "imagenet", uri="s3://data/imagenet/", digest="sha256:ab")
    capsys.readouterr()
    assert _invoke(tmp_path, dict(action="resolve", model_name="imagenet", json=True)) == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["kind"], out["uri"], out["digest"]) == ("dataset", "s3://data/imagenet/", "sha256:ab")
    assert _invoke(tmp_path, dict(action="show", model_name="imagenet")) == 0
    assert "Kind: dataset" in capsys.readouterr().out


def test_delete_consumed_version_warns_consumer_count(tmp_path, caplog):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    record_use(storage, "resnet", n, "serving", "1.0")
    record_use(storage, "resnet", n, "eval", "2.0")
    with caplog.at_level(logging.WARNING):
        rc = _invoke(tmp_path, dict(action="delete", model_name="resnet", version_ref=str(n)))
    assert rc == 0
    assert "used by 2 runs" in caplog.text


def test_delete_unused_version_does_not_warn(tmp_path, caplog):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    n = register_version(storage, "resnet", {"app": "a", "verstr": "0.1"})
    with caplog.at_level(logging.WARNING):
        assert _invoke(tmp_path, dict(action="delete", model_name="resnet", version_ref=str(n))) == 0
    assert "used by" not in caplog.text
