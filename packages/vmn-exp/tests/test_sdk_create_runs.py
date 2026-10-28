"""``vmn_exp.sdk.create_runs``: pre-register a batch of waiting runs git-free,
the way a launcher registers a study's trials before any pod starts.

The batch shares its parent, code identity and environment, and costs the
store one claim, marker and create entry per run; the code version's runs are
listed once per batch, never per run.
"""
import boto3
import pytest
from moto import mock_aws

import vmn_exp.sdk.create as sdk_create
from vmn_exp.core import run_hint
from vmn_exp.sdk import RunExistsError, create_run, create_runs, start_run
from vmn_exp.sdk.reader import list_runs
from vmn_exp.storage import s3_stats
from vmn_exp.storage.s3 import S3SnapshotStorage

BUCKET = "vmn-bucket"
APP = "app"
CODE = "2.0.251-dev.852cb2d.0000000"


@pytest.fixture(autouse=True)
def _s3(monkeypatch):
    for k, v in dict(
        AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x", AWS_DEFAULT_REGION="us-east-1"
    ).items():
        monkeypatch.setenv(k, v)
    for var in ("VMN_WRITER_ID", "VMN_EXP_OFFLINE", "VMN_EXPERIMENT_DIR",
                "VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(var, raising=False)
    run_hint.clear()  # each test's bucket is a new store under the same name
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture(autouse=True)
def snapshot_meta(tmp_path, monkeypatch):
    path = tmp_path / "vmn_metadata.yml"
    path.write_text(
        f"verstr: {CODE}\napp_name: {APP}\n"
        "base_version: 2.0.251\nbase_commit: 852cb2d\nbranch: master\n"
    )
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(path))
    monkeypatch.chdir(tmp_path)
    return str(path)


@pytest.fixture
def storage():
    return S3SnapshotStorage(BUCKET, prefix="exps/runs")


@pytest.fixture
def calls():
    seen = []
    s3_stats.add_listener(seen.append)
    yield seen
    s3_stats.remove_listener(seen.append)


def _rows(storage):
    return {r["verstr"]: r for r in list_runs(APP, storage=storage, use_index=False)}


def _trials(count):
    return [{"name": f"trial{i}", "params": {"trial_id": i}, "tags": {"kind": "trial"}}
            for i in range(count)]


def _study(storage):
    return create_run(APP, name="study", tags={"kind": "study"}, storage=storage,
                      capture_env=False)


def test_a_study_pre_registers_its_trials_and_a_pod_takes_one(storage):
    study = _study(storage)

    trials = create_runs(APP, _trials(5), parent=study, storage=storage)

    assert len(set(trials)) == 5 and study not in trials
    rows = _rows(storage)
    for i, verstr in enumerate(trials):
        row = rows[verstr]
        assert (row["name"], row["parent"], row["status"]) == (f"trial{i}", study, "created")
        assert row["params"]["trial_id"] == i
        assert row["tags"] == {"kind": "trial"}
    assert rows[study]["tags"] == {"kind": "study"}

    with start_run(APP, run_id=trials[3], storage=storage, system_metrics=False) as pod:
        assert pod.id == trials[3]
        pod.log_metric("value", 0.25)

    row = _rows(storage)[trials[3]]
    assert row["status"] == "succeeded"
    assert row["metrics"]["value"] == 0.25
    assert row["tags"] == {"kind": "trial"}
    assert row["parent"] == study


def test_exact_run_ids_are_claimed_as_given_in_order(storage):
    ids = [f"{CODE}.trial-{i}" for i in (7, 2, 9)]

    got = create_runs(APP, [{"run_id": i, "name": i[-7:]} for i in ids], storage=storage)

    assert got == ids
    assert {_rows(storage)[i]["name"] for i in ids} == {"trial-7", "trial-2", "trial-9"}


def test_allocated_names_never_take_an_exact_run_id_of_the_batch(storage):
    taken = f"{CODE}.r2"

    got = create_runs(APP, [{"name": "a"}, {"run_id": taken, "name": "b"}, {"name": "c"}],
                      storage=storage)

    assert got[1] == taken and len(set(got)) == 3
    assert [_rows(storage)[v]["name"] for v in got] == ["a", "b", "c"]


def _batch_requests(calls, storage, count, **kwargs):
    study = _study(storage)
    calls.clear()
    created = create_runs(APP, _trials(count), parent=study, storage=storage, **kwargs)
    records = tuple(storage._record_prefix(APP, v) + "/" for v in created)
    listings = [c.key for c in calls if c.operation == "ListObjectsV2"
                and not (c.key or "").startswith(records)]
    return calls, listings


@pytest.mark.parametrize("count", [10, 40])
def test_a_batch_lists_the_code_versions_runs_once(calls, storage, count):
    requests, listings = _batch_requests(calls, storage, count)

    assert len(listings) <= 1, listings
    # A run: its claim (HEAD + PUT), metadata, parent marker and create entry
    # (the append's listing of its own, new record + PUT).
    assert len(requests) <= 6 * count + 4, len(requests)


def test_later_registrations_of_the_process_claim_past_its_last_without_listing(
        calls, storage):
    _study(storage)
    calls.clear()

    created = [create_run(APP, name=f"date{i}", storage=storage, capture_env=False)
               for i in range(3)]
    created += create_runs(APP, _trials(3), storage=storage)

    records = tuple(storage._record_prefix(APP, v) + "/" for v in created)
    assert [c.key for c in calls if c.operation == "ListObjectsV2"
            and not (c.key or "").startswith(records)] == []
    assert len(set(created)) == 6


def test_names_another_launcher_claimed_meanwhile_cost_one_more_listing(calls, storage):
    for verstr in [CODE] + [f"{CODE}.r{n}" for n in range(2, 12)]:
        assert storage.create_exclusive(APP, verstr, {"verstr": verstr}, {})
    real_list, lists = storage.list_run_verstrs, []

    def listed_before_the_other_launcher(app_name, scope):
        lists.append(scope)
        names = real_list(app_name, scope)
        return names if len(lists) > 1 else []

    storage.list_run_verstrs = listed_before_the_other_launcher

    got = create_runs(APP, _trials(8), storage=storage)

    assert sorted(got) == sorted(f"{CODE}.r{n}" for n in range(12, 20))
    assert [_rows(storage)[v]["name"] for v in got] == [f"trial{i}" for i in range(8)]
    assert len(lists) <= 2


def test_a_batch_of_exact_ids_lists_nothing_outside_its_records(calls, storage):
    study = _study(storage)
    calls.clear()

    created = create_runs(APP, [{"run_id": f"{CODE}.t{i}"} for i in range(20)],
                          parent=study, storage=storage)

    records = tuple(storage._record_prefix(APP, v) + "/" for v in created)
    assert [c.key for c in calls if c.operation == "ListObjectsV2"
            and not (c.key or "").startswith(records)] == []


def test_the_batch_resolves_its_parent_and_captures_the_env_once(storage, monkeypatch):
    study = _study(storage)
    resolved, captured = [], []
    real_resolve = sdk_create.resolve_parent
    monkeypatch.setattr(sdk_create, "resolve_parent",
                        lambda *a, **k: resolved.append(a) or real_resolve(*a, **k))
    monkeypatch.setattr(sdk_create, "capture_env_safe",
                        lambda *a: captured.append(a) or {"python": {"version": "3"}})

    create_runs(APP, _trials(6), parent=study, storage=storage, capture_env=True)

    assert len(resolved) == 1
    assert len(captured) == 1


def test_a_taken_run_id_raises_and_keeps_the_existing_record(storage):
    run_id = f"{CODE}.t1"
    create_runs(APP, [{"run_id": run_id, "note": "first"}], storage=storage)

    with pytest.raises(RunExistsError, match="t1"):
        create_runs(APP, [{"run_id": run_id, "note": "second"}], storage=storage)

    assert storage.load_metadata(APP, run_id)["note"] == "first"


def test_exist_ok_re_registers_a_batch_after_an_orchestrator_restart(storage):
    study = _study(storage)
    batch = [{"run_id": f"{CODE}.t{i}", "name": f"trial{i}"} for i in range(3)]
    first = create_runs(APP, batch[:2], parent=study, storage=storage)

    again = create_runs(APP, batch, parent=study, storage=storage, exist_ok=True)

    assert again == first + [f"{CODE}.t2"]
    assert len([v for v in _rows(storage) if v != study]) == 3


@pytest.mark.parametrize("clash", [{"name": "other"}, {"parent": None}])
def test_exist_ok_still_refuses_another_runs_name(storage, clash):
    study = _study(storage)
    run_id = f"{CODE}.t1"
    create_runs(APP, [{"run_id": run_id, "name": "trial1"}], parent=study, storage=storage)
    item = {"run_id": run_id, "name": clash.get("name", "trial1")}
    parent = clash.get("parent", study)

    with pytest.raises(RunExistsError):
        create_runs(APP, [item], parent=parent, storage=storage, exist_ok=True)


@pytest.mark.parametrize("runs", [
    [{"run_id": f"{CODE}.t1"}, {"run_id": "9.9.9-dev.other.0000000.t2"}],
    [{"run_id": f"{CODE}.t1"}, {"run_id": f"{CODE}.t1"}],
    [{"name": "a"}, {"nmae": "typo"}],
    [{"name": "a"}, {"tags": {"": "x"}}],
])
def test_a_bad_item_refuses_the_batch_before_anything_is_created(storage, runs):
    with pytest.raises(ValueError):
        create_runs(APP, runs, storage=storage)

    assert storage.list_verstrs(APP) == []


def test_an_empty_batch_creates_nothing(storage):
    assert create_runs(APP, [], storage=storage) == []
    assert storage.list_verstrs(APP) == []
