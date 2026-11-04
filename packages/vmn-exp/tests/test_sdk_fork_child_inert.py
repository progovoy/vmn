"""A forked child never writes the parent's run (plan 30 W2, gaps G4 and G5).

The child inherits the parent's ``Run`` object: recording on it is dropped
with one warning, ``finish()``/``release()``/``detach()`` and the context
manager's exit do nothing, ``current_run()`` is None, and ``start_run()``
there opens a new inner run of its own. Each scenario runs in its own
interpreter (git-free container mode), so forking never touches pytest's.
"""
import os
import subprocess
import sys

import pytest
import yaml
from exp_helpers import _PY, _SRC_PATH

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork") or sys.platform == "win32", reason="needs fork"
)

_PRELUDE = r"""
import json, logging, os, sys, time, traceback
from vmn_exp.core.status import load_run_state
from vmn_exp.sdk import context, log_buffer, start_run

APP = "trainer"
# Nothing reaches the store unless someone flushes: a child that ships the
# parent's queued entries shows up as a changed log.
log_buffer.FLUSH_INTERVAL_SEC = 3600


class Inert(logging.Handler):
    records = []

    def emit(self, record):
        if "was opened by pid" in record.getMessage():
            Inert.records.append(record.getMessage())


logging.getLogger("vmn_exp").addHandler(Inert(level=logging.WARNING))

run = start_run(name="parent", system_metrics=False, heartbeat_interval_sec=60)
storage = run._storage
run.log_note("before the fork")
run._log_buffer.flush()
run.log_note("queued at the fork")


def log_of(r):
    return [e for e in storage.load_merged_log(APP, r.id)]


def state_of(r):
    state = dict(load_run_state(storage, APP, r.id))
    for key in ("heartbeat", "heartbeat_seq"):
        state.pop(key, None)
    return state


def notes(r):
    return [e["text"] for e in log_of(r) if e.get("type") == "note"]


def wait_child(pid, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.WEXITSTATUS(status)
        time.sleep(0.05)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    print("HUNG: the forked child deadlocked")
    sys.exit(75)
"""

_INHERITED_RUN_IS_INERT = _PRELUDE + r"""
artifact = os.path.join(sys.argv[1], "weights.bin")
with open(artifact, "wb") as f:
    f.write(b"w")
log_before, state_before = log_of(run), state_of(run)

pid = os.fork()
if pid == 0:
    code = 0
    try:
        with run:
            run.log_metrics({"loss": 1.0})
            run.log_metric("acc", 0.5, step=3)
            run.log_note("from the child")
            run.log_params({"child": 1})
            run.set_tags({"who": "child"})
            run.log_histogram("h", [1.0, 2.0, 3.0])
            run.log_artifact(artifact)
            if run.alert("from the child") is not False:
                code = 2
        run.finish(exit_code=3)
        run.release()
        run.detach()
        if context.current_run() is not None:
            code = 3
        if len(Inert.records) != 1:
            code = 4
            print("warnings:", Inert.records, file=sys.stderr)
        elif f"pid {os.getppid()}" not in Inert.records[0] or run.id not in Inert.records[0]:
            code = 5
            print("warning:", Inert.records[0], file=sys.stderr)
    except BaseException:
        traceback.print_exc()
        code = 9
    sys.stderr.flush()
    os._exit(code)

code = wait_child(pid, 30)
assert code == 0, f"child exit {code}"
assert log_of(run) == log_before, "the child wrote the parent's log"
assert state_of(run) == state_before, "the child changed the parent's state"
assert storage.list_artifacts(APP, run.id) in ([], None) or not any(
    "weights" in str(a) for a in storage.list_artifacts(APP, run.id)), "child stored an artifact"
assert context.current_run() is run
assert not Inert.records, "the parent warned"
assert run.finish() is True
state = load_run_state(storage, APP, run.id)
assert state["state"] == "finished" and state["exit_code"] == 0, state
assert notes(run) == ["before the fork", "queued at the fork"], notes(run)
print("OK")
"""

_CHILD_STARTS_ITS_OWN_RUN = _PRELUDE + r"""
log_before, state_before = log_of(run), state_of(run)
read_fd, write_fd = os.pipe()
pid = os.fork()
if pid == 0:
    code = 0
    try:
        inner = start_run(name="inner", system_metrics=False, heartbeat_interval_sec=60)
        if inner is run or inner.pid != os.getpid():
            code = 2
        if context.current_run() is not inner:
            code = 3
        if inner._log_buffer is run._log_buffer or inner._gate is run._gate:
            code = 4
        inner.log_metrics({"loss": 0.25})
        inner.log_note("inner note")
        if inner.finish() is not True:
            code = 5
        if Inert.records:
            code = 6
        os.write(write_fd, inner.id.encode())
    except BaseException:
        traceback.print_exc()
        code = 9
    sys.stderr.flush()
    os._exit(code)
os.close(write_fd)
code = wait_child(pid, 30)
inner_id = os.read(read_fd, 1000).decode()
assert code == 0, f"child exit {code}"

parents = {m["verstr"]: m.get("parent") for m in storage.list_snapshots(APP)}
assert parents[inner_id] == run.id, parents
inner_state = load_run_state(storage, APP, inner_id)
assert inner_state["state"] == "finished" and inner_state["exit_code"] == 0, inner_state
inner_log = storage.load_merged_log(APP, inner_id)
assert any(e.get("type") == "metrics" and e.get("values", {}).get("loss") == 0.25
           for e in inner_log), inner_log
assert log_of(run) == log_before and state_of(run) == state_before
assert os.environ["VMN_EXPERIMENT_ID"] == run.id
assert run.finish() is True
assert notes(run) == ["before the fork", "queued at the fork"], notes(run)
print("OK")
"""


def _run_script(script, tmp_path):
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump({
        "verstr": "0.0.1-dev.abc1234.def5678",
        "app_name": "trainer",
        "base_version": "0.0.1",
        "base_commit": "abc1234" * 5 + "abcde",
        "branch": "main",
    }))
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("VMN_EXPERIMENT", "VMN_APP_NAME", "VMN_WORKING_DIR"))}
    env.update(
        PYTHONPATH=_SRC_PATH,
        VMN_SNAPSHOT_METADATA=str(image / "vmn_metadata.yml"),
        VMN_EXPERIMENT_DIR=str(tmp_path / "store"),
        VMN_CAPTURE_ENV="0",
    )
    return subprocess.run(
        [_PY, "-c", script, str(tmp_path)],
        env=env, cwd=str(image), capture_output=True, text=True, timeout=120,
    )


def test_an_inherited_run_records_and_finalizes_nothing_in_the_child(tmp_path):
    proc = _run_script(_INHERITED_RUN_IS_INERT, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_start_run_in_the_child_opens_its_own_inner_run(tmp_path):
    proc = _run_script(_CHILD_STARTS_ITS_OWN_RUN, tmp_path)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_an_inherited_log_buffer_writes_nothing_in_the_child(tmp_path):
    from vmn_exp.sdk.log_buffer import LogBuffer

    written = tmp_path / "written.txt"

    def write(entries):
        with open(written, "a") as f:
            f.write("".join(f"{e['n']}\n" for e in entries))

    buf = LogBuffer(write)
    buf.append({"n": "parent queued"})
    pid = os.fork()
    if pid == 0:
        try:
            buf.append({"n": "child"})
            buf.flush()
            buf.close()
            buf.append({"n": "child after close"})
        finally:
            os._exit(0)
    os.waitpid(pid, 0)
    assert not written.exists(), written.read_text()
    buf.close()
    assert written.read_text() == "parent queued\n"
