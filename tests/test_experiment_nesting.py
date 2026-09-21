"""Outer/inner experiment nesting: `vmn exp run` links the runs it spawns."""
import os
import stat
import sys

from version_stamp.cli.entry import vmn_run
from version_stamp.core.experiment_tree import INNER, OUTER, annotate_tree
from version_stamp.core.logging import reset_logger
from helpers import (
    DEV_VERSION_RE,
    extract_dev_verstr,
    _experiment,
    _init_app,
    _run_vmn_init,
    _stamp_app,
)

_PY = sys.executable or "python3"
# Nested runs are real subprocesses; they must import the version_stamp under
# test, not the one the venv has installed editable from the main checkout.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _storage(app_layout):
    from version_stamp.cli.snapshot import get_snapshot_storage

    return get_snapshot_storage(
        "local", vmn_root_path=app_layout.repo_path, subdir="experiments"
    )


def _exp(*argv):
    reset_logger()
    return vmn_run(["exp"] + list(argv))[0]


def _last_dev_verstr(output):
    """The last dev verstr printed — nested runs print theirs first."""
    found = None
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line.startswith("[") and DEV_VERSION_RE.match(line):
            found = line
    return found


def _exp_run(app_name, run_cmd, extra=None):
    args = ["exp", "run", app_name] + list(extra or []) + ["--"] + list(run_cmd)
    reset_logger()
    return vmn_run(args)[0]


def _bootstrap(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def _metadata(app_layout, verstr):
    meta, _ = _storage(app_layout).load(app_layout.app_name, verstr)
    return meta


def _write_sweep_script(app_layout, body):
    path = os.path.join(app_layout.repo_path, "sweep.sh")
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


def test_create_without_parent_omits_the_key(app_layout, capfd):
    _bootstrap(app_layout)
    os.environ.pop("VMN_EXPERIMENT_ID", None)

    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    assert "parent" not in _metadata(app_layout, verstr)


def test_env_experiment_id_becomes_parent(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="outer") == 0
    outer = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = outer
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note="inner") == 0
        inner = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    assert _metadata(app_layout, inner)["parent"] == outer


def test_parent_flag_overrides_env_and_resolves_references(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="a") == 0
    first = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = "0.0.0-dev.bogus"
    try:
        capfd.readouterr()
        assert _exp("create", app_layout.app_name, "--parent", "@1") == 0
        child = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    assert _metadata(app_layout, child)["parent"] == first

    capfd.readouterr()
    assert _exp("create", app_layout.app_name, "--parent", "latest") == 0
    grandchild = extract_dev_verstr(capfd.readouterr().out)
    assert _metadata(app_layout, grandchild)["parent"] == child


def test_unknown_parent_reference_fails(app_layout, capfd):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _exp("create", app_layout.app_name, "--parent", "@9") != 0


def test_stale_env_experiment_id_is_ignored(app_layout, capfd):
    """A pruned outer run must not fail — or mis-parent — someone's training run."""
    _bootstrap(app_layout)

    os.environ["VMN_EXPERIMENT_ID"] = "0.0.1-dev.deadbeef"
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name) == 0
        verstr = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    assert "parent" not in _metadata(app_layout, verstr)


def test_env_experiment_id_resolves_references(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="outer") == 0
    outer = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = "@1"
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note="inner") == 0
        inner = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    assert _metadata(app_layout, inner)["parent"] == outer


def test_show_reads_run_state_only_within_the_subtree(app_layout, capfd, monkeypatch):
    """`exp show` must not read every experiment's run state to print one Subtree."""
    from version_stamp.cli import experiment as exp_mod

    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="outer") == 0
    outer = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = outer
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note="inner") == 0
        inner = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    unrelated = []
    for i in range(4):
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note=f"other{i}") == 0
        unrelated.append(extract_dev_verstr(capfd.readouterr().out))
    assert len(set(unrelated)) == 4

    reads = []
    real_load = exp_mod.load_run_state

    def _counting(storage, app_name, verstr):
        reads.append(verstr)
        return real_load(storage, app_name, verstr)

    monkeypatch.setattr(exp_mod, "load_run_state", _counting)
    capfd.readouterr()
    exp_mod._print_status_block(
        _storage(app_layout),
        app_layout.app_name,
        outer,
        _metadata(app_layout, outer),
    )
    out = capfd.readouterr().out
    assert inner in out, "Children must still be printed"
    assert set(reads) <= {outer, inner}, reads
    assert len(reads) <= 3, reads


def test_show_skips_tree_reads_for_a_lone_experiment(app_layout, capfd, monkeypatch):
    from version_stamp.cli import experiment as exp_mod

    _bootstrap(app_layout)
    os.environ.pop("VMN_EXPERIMENT_ID", None)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="solo") == 0
    solo = extract_dev_verstr(capfd.readouterr().out)

    reads = []
    real_load = exp_mod.load_run_state
    monkeypatch.setattr(
        exp_mod,
        "load_run_state",
        lambda s, a, v: (reads.append(v), real_load(s, a, v))[1],
    )
    exp_mod._print_status_block(
        _storage(app_layout), app_layout.app_name, solo, _metadata(app_layout, solo)
    )
    assert reads == [solo]


def test_experiment_is_never_its_own_parent():
    from version_stamp.cli.experiment import _attach_parent

    meta = {"verstr": "v1"}
    _attach_parent(meta, "v1")
    assert "parent" not in meta

    _attach_parent(meta, None)
    assert "parent" not in meta

    _attach_parent(meta, "v0")
    assert meta["parent"] == "v0"


def test_nested_exp_run_produces_one_outer_and_two_inner(app_layout, capfd):
    _bootstrap(app_layout)

    inner_cmd = (
        f'"{_PY}" -m version_stamp.cli.entry exp run {app_layout.app_name}'
        f' -- "{_PY}" -c "print(1)"'
    )
    _write_sweep_script(app_layout, "#!/bin/sh\nset -e\n" + inner_cmd + "\n" + inner_cmd + "\n")

    capfd.readouterr()
    os.environ["PYTHONPATH"] = _PROJECT_ROOT
    try:
        assert _exp_run(app_layout.app_name, ["/bin/sh", "sweep.sh"]) == 0
    finally:
        os.environ.pop("PYTHONPATH", None)
    outer = _last_dev_verstr(capfd.readouterr().out)
    assert outer is not None

    metas = _storage(app_layout).list_snapshots(app_layout.app_name)
    children = [m["verstr"] for m in metas if m.get("parent") == outer]
    assert len(children) == 2, [m["verstr"] for m in metas]

    rows = annotate_tree(
        [
            {"verstr": m["verstr"], "parent": m.get("parent"), "status": "succeeded"}
            for m in metas
        ]
    )
    by_verstr = {r["verstr"]: r for r in rows}
    assert by_verstr[outer]["kind"] == OUTER
    assert by_verstr[outer]["depth"] == 0
    for child in children:
        assert by_verstr[child]["kind"] == INNER
        assert by_verstr[child]["depth"] == 1


def test_exp_list_indents_inner_runs(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="outer") == 0
    outer = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = outer
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note="inner") == 0
        inner = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    lines = [ln for ln in capfd.readouterr().out.splitlines() if ln.strip()]
    outer_line = next(ln for ln in lines if outer in ln and inner not in ln)
    inner_line = next(ln for ln in lines if inner in ln)
    assert not outer_line.startswith(" ")
    assert inner_line.startswith("  ")


def test_exp_show_prints_parent_and_children(app_layout, capfd):
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="outer") == 0
    outer = extract_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = outer
    try:
        capfd.readouterr()
        assert _experiment(app_layout.app_name, note="inner") == 0
        inner = extract_dev_verstr(capfd.readouterr().out)
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=inner) == 0
    out = capfd.readouterr().out
    assert "Parent:" in out
    assert outer in out

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=outer) == 0
    out = capfd.readouterr().out
    assert "Children:" in out
    assert inner in out


def test_exp_show_reports_a_subtree_status_that_differs(app_layout, capfd):
    """`exp list` flags a sweep whose trial failed; `show` must agree."""
    _bootstrap(app_layout)

    capfd.readouterr()
    assert _exp_run(app_layout.app_name, [_PY, "-c", "print(1)"]) == 0
    outer = _last_dev_verstr(capfd.readouterr().out)

    os.environ["VMN_EXPERIMENT_ID"] = outer
    try:
        capfd.readouterr()
        assert _exp_run(app_layout.app_name, [_PY, "-c", "import sys;sys.exit(3)"]) == 3
    finally:
        os.environ.pop("VMN_EXPERIMENT_ID", None)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=outer) == 0
    out = capfd.readouterr().out
    assert "Status:" in out
    assert "succeeded" in out, "the sweep's own command exited 0"
    assert "Subtree:" in out, "a failed trial must be visible on the outer run"
    assert "failed" in out
