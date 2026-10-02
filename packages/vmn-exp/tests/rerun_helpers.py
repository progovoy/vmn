"""Shared setup of the ``vmn-exp rerun`` tests: an original run whose code
(a working-tree edit and an untracked script) is gone from the live tree."""
import os
import subprocess

from exp_helpers import _PY, _bootstrap, _exp, _storage

from vmn_exp.core.code_store import code_storage

# Reads the tracked value.txt (edited, uncommitted, at the original run) and
# records it: a rerun reporting the original value ran the original code.
TRAIN = (
    "import os\n"
    "v = open('value.txt').read().strip()\n"
    "with open(os.environ['VMN_METRICS_FILE'], 'a') as f:\n"
    "    f.write(f'v={v}\\n')\n"
    "print('trained on', v)\n"
)


def repo(app_layout):
    return app_layout.repo_path


def write(app_layout, name, content):
    path = os.path.join(repo(app_layout), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def read(app_layout, name):
    with open(os.path.join(repo(app_layout), name)) as f:
        return f.read()


def run_names(app_layout):
    return set(_storage(app_layout).list_record_names(app_layout.app_name))


def code_objects(app_layout):
    return set(code_storage(_storage(app_layout)).list_record_names(app_layout.app_name))


def meta(app_layout, verstr):
    return _storage(app_layout).load_metadata(app_layout.app_name, verstr)


def log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def metric_values(app_layout, verstr, key="v"):
    return [
        e["values"][key] for e in log(app_layout, verstr)
        if e.get("type") == "metrics" and key in e.get("values", {})
    ]


def original_run(app_layout, run_cmd=None, script_dir="", extra_args=None):
    """Stamp, commit value.txt=0, edit it to 1 (uncommitted), add the untracked
    train.py, run it, then move the live tree on (value 2). Returns the verstr."""
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "value.txt", "0\n")
    write(app_layout, "value.txt", "1\n")
    write(app_layout, os.path.join(script_dir, "train.py"), TRAIN)
    before = run_names(app_layout)
    assert _exp(app_layout.app_name, action="run",
                run_cmd=run_cmd or [_PY, "train.py"], extra_args=extra_args) == 0
    (verstr,) = run_names(app_layout) - before
    write(app_layout, "value.txt", "2\n")
    return verstr


def rerun(app_layout, verstr=None, extra_args=None, run_cmd=None):
    """``(exit code, new run verstr or None)``."""
    before = run_names(app_layout)
    rc = _exp(app_layout.app_name, action="rerun", version=verstr,
              extra_args=extra_args, run_cmd=run_cmd)
    new = run_names(app_layout) - before
    assert len(new) <= 1, new
    return rc, (new.pop() if new else None)


def worktrees(app_layout):
    out = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo(app_layout),
        capture_output=True, text=True, check=True,
    ).stdout
    return [line for line in out.splitlines() if line.startswith("worktree ")]
