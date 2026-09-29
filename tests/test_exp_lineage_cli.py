"""``vmn-exp lineage <app> -v <ref> [--depth N] [--json]``."""
import hashlib
import json

from helpers import _bootstrap, _exp, _storage

from vmn_exp.core.lineage import artifact_ref_uri


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _attach(app_layout, verstr, path):
    assert _exp(app_layout.app_name, action="add", version=verstr, attach=str(path)) == 0


def _run(capfd, app_layout, *extra, version=None):
    capfd.readouterr()
    rc = _exp(app_layout.app_name, action="lineage", version=version, extra_args=list(extra))
    return rc, capfd.readouterr().out


def _chain(app_layout, tmp_path):
    """prep (data.csv) → train (input by digest) (model.pkl) → eval (vmn://)."""
    _bootstrap(app_layout)
    data = tmp_path / "data.csv"
    data.write_text("a,b\n")
    prep = _create(app_layout)
    _attach(app_layout, prep, data)
    sha = hashlib.sha256(b"a,b\n").hexdigest()
    model = tmp_path / "model.pkl"
    model.write_text("m")
    train = _create(app_layout, "--input", f"data=file:///mnt/data.csv#sha256:{sha}")
    _attach(app_layout, train, model)
    uri = artifact_ref_uri(app_layout.app_name, train, "model.pkl")
    evaluate = _create(app_layout, "--input", f"model={uri}")
    return prep, train, evaluate


def test_lineage_json(app_layout, capfd, tmp_path):
    prep, train, evaluate = _chain(app_layout, tmp_path)
    rc, out = _run(capfd, app_layout, "--json", version=train)
    assert rc == 0
    payload = json.loads(out)
    assert payload["verstr"] == train
    assert [n["verstr"] for n in payload["upstream"]] == [prep]
    assert [n["verstr"] for n in payload["downstream"]] == [evaluate]
    assert payload["models"] == []


def test_lineage_depth(app_layout, capfd, tmp_path):
    prep, train, evaluate = _chain(app_layout, tmp_path)
    rc, out = _run(capfd, app_layout, "--json", "--depth", "2", version=evaluate)
    assert rc == 0
    assert [(n["verstr"], n["depth"]) for n in json.loads(out)["upstream"]] == [
        (train, 1), (prep, 2),
    ]


def test_lineage_text(app_layout, capfd, tmp_path):
    prep, train, evaluate = _chain(app_layout, tmp_path)
    rc, out = _run(capfd, app_layout, version=train)
    assert rc == 0
    assert f"Lineage: {train}" in out
    upstream, downstream = out.split("Downstream")
    assert prep in upstream and "data <- data.csv (digest)" in upstream
    assert evaluate in downstream and "model <- model.pkl (uri)" in downstream


def test_lineage_no_links(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    lone = _create(app_layout)
    rc, out = _run(capfd, app_layout, version=lone)
    assert rc == 0
    assert "Upstream:   none" in out and "Downstream: none" in out


def test_lineage_unknown_ref(app_layout, capfd):
    _bootstrap(app_layout)
    _create(app_layout)
    rc, _ = _run(capfd, app_layout, version="@9")
    assert rc == 1


def test_lineage_cli_prints_used_model_and_datasets(app_layout, capfd, tmp_path):
    from vmn_exp.registry.names import registry_uri
    from vmn_exp.registry.store import ensure_model, register_version
    from vmn_exp.sdk.datasets import register_dataset

    _, train, _ = _chain(app_layout, tmp_path)
    storage = _storage(app_layout)
    ensure_model(storage, "clf")
    register_version(storage, "clf", {"app": app_layout.app_name, "verstr": train},
                     artifact_path="model.pkl")
    data = tmp_path / "ref.csv"
    data.write_text("x\n")
    register_dataset("ds", str(data), storage=storage)
    uri = artifact_ref_uri(app_layout.app_name, train, "model.pkl")
    serve = _create(app_layout, "--input", f"clf={uri}", "--input", f"ds={registry_uri('ds', 1)}")

    rc, out = _run(capfd, app_layout, version=serve)
    assert rc == 0
    assert "clf <- model.pkl (uri)  model clf v1" in out
    assert "Datasets:" in out and "ds v1  (input ds)" in out
