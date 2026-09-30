"""``vmn-exp rewind <app> -v <ref> --step N``: hide a finished run's history
past a step without reopening it (the CLI side of ``rewind_to_step``)."""
import datetime

import boto3
import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage
from moto import mock_aws

from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.log import latest_metrics, load_log, metric_series
from vmn_exp.core.status import RUN_STATE_FILE, load_run_state
from vmn_exp.sdk import start_run
from vmn_exp.sdk.reader import list_runs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                "VMN_SNAPSHOT_METADATA", "VMN_EXPERIMENT_STORE", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)


def _source(app_layout, steps=4):
    with start_run(app_layout.app_name, params={"lr": 0.1}) as run:
        for step in range(1, steps + 1):
            run.log_metric("loss", 1.0 / step, step=step)
    return run.id


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _steps(log):
    return [(p["step"], p["value"]) for p in metric_series(log).get("loss", [])]


def _rewind(app_layout, *args):
    return _exp(app_layout.app_name, action="rewind", extra_args=list(args))


def test_rewind_hides_later_history_everywhere(app_layout, capfd):
    _bootstrap(app_layout)
    source = _source(app_layout)
    capfd.readouterr()

    assert _rewind(app_layout, "-v", source, "--step", "2") == 0
    assert f"rewound {source} to step 2 (hid 2 entries)" in capfd.readouterr().out

    log = _log(app_layout, source)
    assert log[-1]["type"] == "rewind" and log[-1]["step"] == 2
    assert _steps(log) == [(1, 1.0), (2, 0.5)]
    assert latest_metrics(log)["loss"] == 0.5
    assert list_runs(app_layout.app_name)[0]["metrics"]["loss"] == 0.5
    index = ExperimentIndex(_storage(app_layout), app_layout.app_name)
    index.refresh()
    assert index.rows()[0]["metrics"]["loss"] == 0.5

    assert _exp(app_layout.app_name, action="show", version=source) == 0
    out = capfd.readouterr().out
    assert "Rewound to step 2" in out
    assert "0.25" not in out


def test_rewind_resolves_refs_like_other_actions(app_layout, capfd):
    _bootstrap(app_layout)
    _source(app_layout)
    latest = _source(app_layout, steps=3)
    capfd.readouterr()

    assert _rewind(app_layout, "--latest", "--step", "1") == 0
    assert f"rewound {latest} to step 1 (hid 2 entries)" in capfd.readouterr().out
    assert _rewind(app_layout, "-v", "@2", "--step", "0") == 0
    assert _steps(_log(app_layout, latest)) == []


def test_rewinding_again_hides_nothing_new(app_layout, capfd):
    _bootstrap(app_layout)
    source = _source(app_layout)
    assert _rewind(app_layout, "-v", source, "--step", "2") == 0
    capfd.readouterr()

    assert _rewind(app_layout, "-v", source, "--step", "3") == 0
    assert "(hid 0 entries)" in capfd.readouterr().out
    assert _steps(_log(app_layout, source)) == [(1, 1.0), (2, 0.5)]


def test_rewinding_a_running_run_is_refused(app_layout, capfd):
    _bootstrap(app_layout)
    source = _source(app_layout)
    storage = _storage(app_layout)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    state = dict(load_run_state(storage, app_layout.app_name, source))
    state.update(state="running", exit_code=None, finished_at=None, heartbeat=now,
                 host="elsewhere", pid=1)
    storage.save_file(app_layout.app_name, source, RUN_STATE_FILE, yaml.safe_dump(state))
    capfd.readouterr()

    assert _rewind(app_layout, "-v", source, "--step", "1") == 1
    assert "running" in capfd.readouterr().err
    assert _steps(_log(app_layout, source))[-1] == (4, 0.25)


def test_rewind_needs_a_run_and_a_step(app_layout):
    _bootstrap(app_layout)
    source = _source(app_layout)

    assert _rewind(app_layout, "--step", "1") == 1
    assert _rewind(app_layout, "-v", source) == 1
    assert _rewind(app_layout, "-v", source, "--step", "-1") == 1
    assert _rewind(app_layout, "-v", "no-such-run", "--step", "1") == 1
    assert [e for e in _log(app_layout, source) if e.get("type") == "rewind"] == []


# -- git-free, on an S3 store ---------------------------------------------------

BUCKET = "rewind-bucket"
APP = "trainer"


@pytest.fixture
def container(tmp_path, monkeypatch):
    for k, v in dict(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                     AWS_DEFAULT_REGION="us-east-1").items():
        monkeypatch.setenv(k, v)
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump(
        {"verstr": "1.2.0-dev.abc1234.0000000", "app_name": APP,
         "base_version": "1.2.0", "base_commit": "abc1234"}
    ))
    monkeypatch.chdir(image)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


def test_rewind_works_git_free_on_s3(container, capfd):
    from vmn_exp.cli.main import vmn_exp_run
    from vmn_exp.storage.s3 import S3SnapshotStorage

    store = ["--store", f"s3://{BUCKET}/cli"]
    assert vmn_exp_run(["exp", "create", APP, *store])[0] == 0
    remote = S3SnapshotStorage(BUCKET, prefix="cli")
    verstr = remote.list_snapshots(APP)[-1]["verstr"]
    for step in (1, 2, 3):
        remote.append_log_entry(APP, verstr, "w", {
            "timestamp": f"2026-01-01T00:00:0{step}Z", "type": "metrics",
            "step": step, "values": {"loss": 1.0 / step},
        })
    capfd.readouterr()

    assert vmn_exp_run(["exp", "rewind", APP, "-v", verstr, "--step", "1", *store])[0] == 0
    assert "(hid 2 entries)" in capfd.readouterr().out
    log = load_log(remote, APP, verstr)
    assert [p["step"] for p in metric_series(log).get("loss", [])] == [1]
