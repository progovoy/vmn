"""Failure context in run detail (plan 20 K4): ``output_tail``, ``last_step``
and ``last_good``, present only for failed and stuck runs."""
import datetime
import os

import pytest
from run_code_seed import (
    client,
    finished_state,
    metrics,
    run_url,
    seed_run,
    write_output,
)

pytest.importorskip("fastapi")

TRAIN = ("python", "train.py")
FAILED = "0.0.1-dev.r2"
K4_FIELDS = ("output_tail", "last_step", "last_good")


def _detail(app_layout, verstr):
    resp = client(app_layout).get(run_url(app_layout, verstr))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _failed(app_layout, entries=(), output=None, command=TRAIN):
    seed_run(app_layout, "0.0.1-dev.r1", 1, finished_state(0, TRAIN), name="good")
    seed_run(app_layout, FAILED, 2, finished_state(1, command), entries=entries)
    if output is not None:
        write_output(app_layout, FAILED, output)


def _lines(n, width=10):
    return "".join(f"line {i:04d} " + "x" * width + "\n" for i in range(n)).encode()


def test_a_short_output_is_served_whole(app_layout):
    _failed(app_layout, output=b"epoch 1\nTraceback\nValueError: bad lr\n")
    tail = _detail(app_layout, FAILED)["output_tail"]
    assert tail == {"lines": ["epoch 1", "Traceback", "ValueError: bad lr"], "truncated": False}


def test_only_the_last_40_lines_are_served(app_layout):
    _failed(app_layout, output=_lines(100))
    tail = _detail(app_layout, FAILED)["output_tail"]
    assert tail["truncated"] is True
    assert len(tail["lines"]) == 40
    assert tail["lines"][0].startswith("line 0060 ")
    assert tail["lines"][-1].startswith("line 0099 ")


def test_a_large_output_is_range_read_within_16_kb(app_layout, monkeypatch):
    from vmn_exp.storage.local import LocalSnapshotStorage

    reads = []
    original = LocalSnapshotStorage.read_range

    def spy(self, app_name, verstr, name, offset, length):
        reads.append((name, offset, length))
        return original(self, app_name, verstr, name, offset, length)

    monkeypatch.setattr(LocalSnapshotStorage, "read_range", spy)
    data = _lines(20, width=2000)  # ~40 KB in 20 long lines
    _failed(app_layout, output=data)
    tail = _detail(app_layout, FAILED)["output_tail"]
    output_reads = [r for r in reads if r[0] == "outputs/output.log"]
    assert output_reads and all(length <= 16 * 1024 for _, _, length in output_reads)
    assert sum(len(line.encode()) for line in tail["lines"]) <= 16 * 1024
    assert tail["truncated"] is True
    assert tail["lines"][-1] == data.decode().splitlines()[-1]
    assert all(line.startswith("line ") for line in tail["lines"])  # no partial first line


def test_a_carriage_return_keeps_what_the_terminal_showed(app_layout):
    _failed(app_layout, output=b"epoch 1  10%\repoch 1 100%\nboom\n")
    assert _detail(app_layout, FAILED)["output_tail"]["lines"] == ["epoch 1 100%", "boom"]


def test_no_output_log_is_a_null_tail(app_layout):
    _failed(app_layout)
    assert _detail(app_layout, FAILED)["output_tail"] is None


def test_last_step_is_the_highest_step_of_the_epochs_param(app_layout):
    entries = [{"type": "create", "params": {"epochs": 86}}]
    entries += [metrics({"loss": 1.0 / (s + 1)}, step=s) for s in range(39)]
    _failed(app_layout, entries=entries)
    assert _detail(app_layout, FAILED)["last_step"] == {"step": 38, "of": 86}


def test_last_step_of_max_steps_and_a_non_numeric_total(app_layout):
    entries = [{"type": "create", "params": {"max_steps": "lots"}}, metrics({"loss": 1}, step=5)]
    _failed(app_layout, entries=entries)
    assert _detail(app_layout, FAILED)["last_step"] == {"step": 5, "of": None}


def test_no_stepped_metric_is_a_null_last_step(app_layout):
    _failed(app_layout, entries=[metrics({"loss": 1})])
    assert _detail(app_layout, FAILED)["last_step"] is None


def test_last_good_is_the_latest_earlier_success_of_the_same_command(app_layout):
    _failed(app_layout)
    good = _detail(app_layout, "0.0.1-dev.r1")
    assert _detail(app_layout, FAILED)["last_good"] == {
        "verstr": "0.0.1-dev.r1", "idx": good["idx"], "name": "good",
    }


def test_no_success_of_the_command_is_a_null_last_good(app_layout):
    _failed(app_layout, command=("python", "other.py"))
    assert _detail(app_layout, FAILED)["last_good"] is None


def test_a_succeeded_run_carries_none_of_the_fields(app_layout):
    _failed(app_layout, output=b"fine\n")
    detail = _detail(app_layout, "0.0.1-dev.r1")
    assert not any(field in detail for field in K4_FIELDS)


def test_a_stuck_run_carries_them(app_layout):
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = dict(finished_state(None, TRAIN), state="running", heartbeat=old,
                 finished_at=None, duration_sec=None)
    path = seed_run(app_layout, "0.0.1-dev.r3", 3, state)
    aged = datetime.datetime.now().timestamp() - 3600
    os.utime(os.path.join(path, "run_state.yml"), (aged, aged))
    write_output(app_layout, "0.0.1-dev.r3", b"hung\n")
    detail = _detail(app_layout, "0.0.1-dev.r3")
    assert detail["status"]["status"] == "stuck"
    assert detail["output_tail"]["lines"] == ["hung"]
    assert set(K4_FIELDS) <= set(detail)
