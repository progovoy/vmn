"""SDK readers open the store the writer records to (plan 45): a NoOpRun reads
start_run's ``storage=``, ``register_model(run=<verstr>, app_name=)`` reads
that app's conf store, and a reader naming no app reads the checkout's sole
app's conf store, as ``start_run`` infers it."""
import pytest

from fakes.clock import FakeClock
from fakes.env import FakeEnv
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.registry.view import resolve_ref
from vmn_exp.sdk import NoOpRun
from vmn_exp.sdk.datasets import register_dataset
from vmn_exp.sdk.models import register_model
from vmn_exp.sdk.store_resolve import storage_of_checkout
from vmn_exp.storage.local import LocalSnapshotStorage

VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"
_STORE_ENV = ("VMN_STORE", "VMN_STORE_BUCKET", "VMN_EXPERIMENT_STORE",
              "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_DIR", "VMN_EXPERIMENT_ID",
              "VMN_APP_NAME", "VMN_WORKING_DIR")


def _store(tmp_path, name):
    return LocalSnapshotStorage(str(tmp_path / name), "runs")


def _outside_any_checkout(tmp_path, monkeypatch):
    for key in _STORE_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)


def _checkout_with_conf_store(tmp_path, app, store_uri):
    conf_dir = tmp_path / "repo" / ".vmn" / app
    conf_dir.mkdir(parents=True)
    (conf_dir / "conf.yml").write_text(f"conf:\n  store:\n    uri: {store_uri}\n")
    return str(tmp_path / "repo")


@pytest.mark.parametrize("use", ["use_model", "use_dataset"])
def test_noop_run_reads_registry_from_start_runs_storage(tmp_path, monkeypatch, use):
    _outside_any_checkout(tmp_path, monkeypatch)
    storage = _store(tmp_path, "run_store")
    kind = use.split("_")[1]
    ensure_model(storage, "m", kind=kind)
    register_version(storage, "m", run_ref={"app": "app", "verstr": VERSTR})
    noop = NoOpRun(app_name="app", rank=1, storage=storage)
    assert getattr(noop, use)("m@1")["n"] == 1


def test_register_model_with_a_verstr_writes_to_the_apps_conf_store(tmp_path, monkeypatch):
    _outside_any_checkout(tmp_path, monkeypatch)
    shared = tmp_path / "shared"
    monkeypatch.chdir(_checkout_with_conf_store(tmp_path, "app", shared.as_uri()))

    register_model("m", run=VERSTR, app_name="app")

    meta = resolve_ref(LocalSnapshotStorage(str(shared), "runs"), "m@1")
    assert meta["run_ref"] == {"app": "app", "verstr": VERSTR}


def test_register_dataset_with_a_verstr_writes_to_the_apps_conf_store(tmp_path, monkeypatch):
    _outside_any_checkout(tmp_path, monkeypatch)
    shared = tmp_path / "shared"
    monkeypatch.chdir(_checkout_with_conf_store(tmp_path, "app", shared.as_uri()))

    register_dataset("d", run=VERSTR, app_name="app", artifact_path="data.csv")

    meta = resolve_ref(LocalSnapshotStorage(str(shared), "runs"), "d@1")
    assert meta["run_ref"] == {"app": "app", "verstr": VERSTR}


def _apps_of(tmp_path, stamped, app_name=None, env=None):
    shared = _store(tmp_path, "shared")
    shared.save("app", VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    root = _checkout_with_conf_store(tmp_path, "app", (tmp_path / "shared").as_uri())
    storage = storage_of_checkout(app_name, root, FakeEnv(env), FakeClock(),
                                  stamped_apps=lambda: stamped)
    return storage.list_apps()


def test_reader_without_an_app_reads_the_sole_stamped_apps_conf_store(tmp_path):
    assert _apps_of(tmp_path, ["app"]) == ["app"]


def test_reader_with_several_stamped_apps_reads_no_conf_store(tmp_path):
    assert _apps_of(tmp_path, ["app", "other"]) == []


def test_vmn_app_name_beats_the_sole_stamped_app(tmp_path):
    assert _apps_of(tmp_path, ["other"], env={"VMN_APP_NAME": "app"}) == ["app"]
