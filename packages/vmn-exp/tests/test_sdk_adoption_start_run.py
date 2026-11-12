"""``start_run()`` in the direct child of ``vmn-exp run`` records into the
supervisor's run (plan 38 A5), or declines when its store does not hold that
run. Driven in container mode (an exported snapshot, a tmp store): no git."""
import logging
import os

import pytest
import yaml

from vmn_exp.sdk import start_run
from vmn_exp.sdk.adoption import ADOPT_PID_ENV, ADOPT_RUN_ID_ENV
from vmn_exp.sdk.guest_run import GuestRun
from vmn_exp.snapshot import open_storage
from vmn_exp.core.real_io import RealClock

APP = "trainer"


@pytest.fixture
def container(tmp_path, monkeypatch):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump({
        "verstr": "0.0.1-dev.abc1234.def5678", "app_name": APP, "base_version": "0.0.1",
        "base_commit": "abc1234" * 5 + "abcde", "branch": "main",
    }))
    monkeypatch.chdir(image)
    for key in ("VMN_WORKING_DIR", "VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_WRITER_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    return tmp_path


def _store(root):
    return open_storage(root=str(root), area="runs", clock=RealClock(), env=os.environ)


def _wrapper_run(monkeypatch, store_dir):
    """A record standing in for the one `vmn-exp run` created, offered to
    this process as to the supervisor's direct child."""
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store_dir))
    with start_run(export_env=False) as wrapper:
        pass
    monkeypatch.setenv("VMN_EXPERIMENT_ID", wrapper.id)
    monkeypatch.setenv(ADOPT_RUN_ID_ENV, wrapper.id)
    monkeypatch.setenv(ADOPT_PID_ENV, str(os.getppid()))
    return wrapper.id


def test_the_direct_child_records_into_the_offered_run(container, monkeypatch):
    verstr = _wrapper_run(monkeypatch, container / "store")

    with start_run(params={"lr": 0.1}, note="adopted", tags={"k": "v"}) as run:
        run.log_metric("loss", 0.25)

    assert isinstance(run, GuestRun) and run.id == verstr
    assert ADOPT_RUN_ID_ENV not in os.environ
    store = _store(container / "store")
    assert [m["verstr"] for m in store.list_snapshots(APP)] == [verstr]
    log = store.load_merged_log(APP, verstr)
    by_type = {e["type"]: e for e in log if e.get("_writer", "").endswith("-sdk")}
    assert by_type["params"]["params"] == {"lr": 0.1}
    assert by_type["note"]["text"] == "adopted"
    assert by_type["tags"]["set"] == {"k": "v"}
    assert any(e.get("values", {}).get("loss") == 0.25 for e in log)


def test_a_second_plain_start_run_in_the_process_nests_under_the_run(container, monkeypatch):
    verstr = _wrapper_run(monkeypatch, container / "store")
    with start_run():
        pass

    with start_run() as second:
        pass

    assert not isinstance(second, GuestRun)
    assert _store(container / "store").load_metadata(APP, second.id)["parent"] == verstr


def test_adoption_is_declined_with_a_warning_when_the_wrapper_record_is_not_in_the_childs_store_and_a_nested_run_is_created(  # noqa: E501
        container, monkeypatch, caplog):
    verstr = _wrapper_run(monkeypatch, container / "wrapper_store")
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(container / "child_store"))

    with caplog.at_level(logging.WARNING, logger="vmn_exp.sdk.guest_run"):
        with start_run() as run:
            pass

    # Each store allocates its own first verstr, so the two may be equal.
    assert not isinstance(run, GuestRun)
    assert "--no-adopt" in caplog.text and verstr in caplog.text
    assert [m["verstr"] for m in _store(container / "child_store").list_snapshots(APP)] == [
        run.id]
    assert [m["verstr"] for m in _store(container / "wrapper_store").list_snapshots(APP)] == [
        verstr]
