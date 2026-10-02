"""Local runs to push, for the ``vmn exp push`` core tests."""
import os

import yaml

from vmn_exp.core.code_store import code_storage, store_code
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.files import log_object_name
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
CODE = "0.0.1-dev.abc1234.0000001"
KEY = CODE + ".abc1234ffff"
X = CODE + ".laptop"
WRITER = "laptop"
PAYLOAD = {"working_tree": "diff --git a/f b/f\n", "untracked_files": b"tarball"}


def local_root(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "root"), area="runs")


def run_meta(verstr=X, **kw):
    return dict(
        {
            "verstr": verstr,
            "timestamp": "2026-01-01T00:00:00Z",
            "base_commit": "abc1234",
            "diff_hash": "ffff",
            "code_verstr": CODE,
            "code": KEY,
        },
        **kw,
    )


def line(i):
    return f'{{"timestamp": "2026-01-01T00:00:{i:02d}Z", "type": "metrics", "i": {i}}}\n'


def add_lines(local, verstr, lines, writer=WRITER):
    path = os.path.join(local._snapshot_dir(APP, verstr), log_object_name(writer))
    with open(path, "a") as f:
        f.write("".join(lines))


def set_state(local, verstr, state, **kw):
    local.save_file(APP, verstr, RUN_STATE_FILE, yaml.dump(dict(kw, state=state)))


def make_run(local, tmp_path, verstr=X, code=True, **meta):
    """A finished local run with a code object, env, two log lines and an artifact."""
    if code:
        store_code(local, APP, KEY, PAYLOAD, {"has_untracked": True})
    local.save(APP, verstr, run_meta(verstr, **meta), {})
    local.save_file(APP, verstr, "env.yml", "python: '3.9'\n")
    add_lines(local, verstr, [line(1), line(2)])
    set_state(local, verstr, "finished", exit_code=0)
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"weights")
    local.save_artifact_file(APP, verstr, str(artifact))
    return verstr


def local_code_exists(local):
    return code_storage(local).exists(APP, KEY)


def remote_log(target, verstr=X, writer=WRITER):
    return b"".join(
        target.load_file(APP, verstr, name) or b""
        for name, _ in target.log_objects(APP, verstr, writer)
    )


def local_log(local, verstr=X, writer=WRITER):
    return local.load_file(APP, verstr, log_object_name(writer))
