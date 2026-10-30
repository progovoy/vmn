"""SDK intents: ``start_run(intent=, intent_keywords=)`` and ``run.set_intent``.

``start_run`` appends the intent once the run opens — a created run, or a
resumed one when an intent is given — and refuses a bad one before creating
anything. ``set_intent`` appends a new entry (the latest wins);
``NoOpRun.set_intent`` records nothing.
"""
import pytest
import yaml
from exp_helpers import _bootstrap, _storage
from vmn_exp.core.fold import fold_intent, fold_log
from vmn_exp.sdk import NoOpRun, start_run
from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                "VMN_SNAPSHOT_METADATA", "VMN_MODE", "RANK", "LOCAL_RANK",
                "WORLD_SIZE", "SLURM_PROCID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def storage(tmp_path):
    st = CachedSnapshotStorage(LocalSnapshotStorage(str(tmp_path / "s"), "runs"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


@pytest.fixture
def run(storage):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    yield run
    run.finish()


def _intents(storage, app_name, verstr):
    return [e for e in storage.load_merged_log(app_name, verstr) if e.get("type") == "intent"]


def _folded(storage, app_name, verstr):
    return fold_intent(fold_log(storage.load_merged_log(app_name, verstr)))


def _runs(app_layout):
    return _storage(app_layout).list_snapshots(app_layout.app_name)


# -- start_run ------------------------------------------------------------------


def test_start_run_records_the_intent(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, intent="focal loss for the long tail",
                   intent_keywords=["Gamma", "gamma", "long tail"]) as run:
        verstr = run.id

    [entry] = _intents(_storage(app_layout), app_layout.app_name, verstr)
    assert entry["text"] == "focal loss for the long tail"
    assert entry["keywords"] == ["Gamma", "long tail"]
    assert entry["source"] == "user"
    assert entry["timestamp"]


def test_start_run_without_an_intent_records_none(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
    assert _intents(_storage(app_layout), app_layout.app_name, verstr) == []


@pytest.mark.parametrize("kwargs", [
    {"intent": "   "},
    {"intent": 5},
    {"intent_keywords": ["orphan"]},
])
def test_a_bad_intent_is_refused_before_a_run_is_created(app_layout, kwargs):
    _bootstrap(app_layout)
    with pytest.raises(ValueError, match="intent"):
        start_run(app_layout.app_name, **kwargs)
    assert _runs(app_layout) == []


@pytest.mark.parametrize("keywords", [5, {"a": 1}])
def test_intent_keywords_of_another_type_are_refused_before_a_run_is_created(app_layout,
                                                                             keywords):
    _bootstrap(app_layout)
    with pytest.raises(ValueError, match="keywords must be a list"):
        start_run(app_layout.app_name, intent="x", intent_keywords=keywords)
    assert _runs(app_layout) == []


def test_resuming_with_an_intent_appends_it(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, intent="first idea") as run:
        verstr = run.id
    with start_run(app_layout.app_name, run_id=verstr, intent="second idea", reopen=True):
        pass

    storage = _storage(app_layout)
    assert [e["text"] for e in _intents(storage, app_layout.app_name, verstr)] == [
        "first idea", "second idea"]
    assert _folded(storage, app_layout.app_name, verstr)["text"] == "second idea"


def test_resuming_without_an_intent_adds_none(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name, intent="first idea") as run:
        verstr = run.id
    with start_run(app_layout.app_name, run_id=verstr, reopen=True):
        pass
    assert len(_intents(_storage(app_layout), app_layout.app_name, verstr)) == 1


# -- Run.set_intent -------------------------------------------------------------


def test_set_intent_appends_and_the_latest_wins(run, storage):
    run.set_intent("first")
    run.set_intent("second", keywords=["k"], generator="claude-opus-5-5")
    run.finish()

    assert [e["text"] for e in _intents(storage, APP, VERSTR)] == ["first", "second"]
    assert _folded(storage, APP, VERSTR) == {
        "text": "second", "keywords": ["k"], "generator": "claude-opus-5-5",
        "source": "user"}


def test_set_intent_works_on_a_finished_run(run, storage):
    run.finish()
    run.set_intent("written afterwards")
    assert _folded(storage, APP, VERSTR)["text"] == "written afterwards"


def test_set_intent_refuses_an_empty_text(run, storage):
    with pytest.raises(ValueError, match="intent"):
        run.set_intent("")
    run.finish()
    assert _intents(storage, APP, VERSTR) == []


# -- NoOpRun --------------------------------------------------------------------


def test_noop_run_set_intent_records_nothing():
    assert NoOpRun("app").set_intent("x", keywords=["k"], generator="g") is None


def test_disabled_start_run_takes_an_intent_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WORKING_DIR", str(tmp_path))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))
    monkeypatch.chdir(tmp_path)

    run = start_run("app", mode="disabled", intent="x", intent_keywords=["k"])
    assert isinstance(run, NoOpRun)
    assert run.set_intent("y") is None
    run.finish()
    assert list(tmp_path.rglob("*")) == []


# -- git-free (VMN_SNAPSHOT_METADATA) -------------------------------------------


def test_git_free_start_run_records_the_intent(tmp_path, monkeypatch):
    meta = tmp_path / "vmn_metadata.yml"
    meta.write_text(yaml.safe_dump(
        {"app_name": APP, "verstr": "0.0.1-dev.abc1234.def5678",
         "base_version": "0.0.1", "changesets": {}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(meta))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "store"))

    with start_run(APP, intent="in the container", intent_keywords="a, b") as run:
        verstr, storage = run.id, run._storage
    assert _folded(storage, APP, verstr) == {
        "text": "in the container", "keywords": ["a", "b"], "source": "user"}
