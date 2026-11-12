"""vmn-exp CLI output goes through the Console port (plan 44 G16): list, show,
compare, diff, export and run write to ``io.console``; stdout/stderr routing
and trailing newlines are as before."""
import argparse
import json

import pytest

from empty_storage import EmptyStorage
from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from fakes.host import FakeHost
from fakes.processes import FakeProcesses
from fakes.random import FakeRandom
from similar_seed import seed, verstr
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli import experiment
from vmn_exp.cli.run import _Supervision
from vmn_exp.cli.views import print_patch
from vmn_exp.core.log import load_log
from vmn_exp.core.ports import IO
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"


@pytest.fixture(autouse=True)
def _logger():
    init_stamp_logger()


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _list_args(**over):
    base = dict(name=APP, sort=None, top=None, last=None, query=None, archived=False,
                json=False)
    return argparse.Namespace(**dict(base, **over))


def _show_args(v, **over):
    return argparse.Namespace(**dict(dict(name=APP, version=[v], json=False), **over))


def test_list_writes_one_line_per_row_to_the_console(storage, capsys):
    a, b = seed(storage, APP, verstr(1), note="first"), seed(storage, APP, verstr(2))
    console = FakeConsole()
    assert experiment.experiment_list(None, None, storage, _list_args(), console, FakeClock()) == 0
    lines = console.stdout.splitlines()
    assert [line.split()[:2] for line in lines] == [["[1]", a], ["[2]", b]]
    assert lines[0].endswith(" - first")
    assert capsys.readouterr() == ("", "")


def test_list_json_is_the_whole_stdout(storage):
    v = seed(storage, APP, verstr(1))
    console = FakeConsole()
    assert experiment.experiment_list(None, None, storage, _list_args(json=True), console, FakeClock()) == 0
    assert [row["verstr"] for row in json.loads(console.stdout)] == [v]


def test_list_of_an_empty_app_says_so_on_out(storage):
    console = FakeConsole()
    assert experiment.experiment_list(None, None, storage, _list_args(), console, FakeClock()) == 0
    assert console.stdout == f"No experiments found for {APP}\n"


def test_show_json_goes_to_out_and_warnings_to_err(storage, capsys):
    v = seed(storage, APP, verstr(1))
    console = FakeConsole()
    assert experiment.experiment_show(None, None, storage, _show_args(v, json=True),
                                      console, FakeClock()) == 0
    assert json.loads(console.stdout)["verstr"] == v
    assert console.stderr == ""

    console = FakeConsole()
    assert experiment.experiment_show(None, None, storage, _show_args(v, patch=True),
                                      console, FakeClock()) == 0
    assert console.stdout.startswith(f"Experiment: {v}\n")
    assert "Status:" in console.stdout
    assert console.stderr.count("\n") == 1 and v in console.stderr
    assert capsys.readouterr() == ("", "")


def test_compare_and_diff_write_to_the_console(storage, capsys, monkeypatch):
    a = seed(storage, APP, verstr(1), params={"lr": 0.1}, metrics={"loss": 0.5})
    b = seed(storage, APP, verstr(2), params={"lr": 0.2}, metrics={"loss": 0.4})
    console = FakeConsole()
    args = argparse.Namespace(name=APP, version=[a, b], json=True)
    assert experiment.experiment_compare(None, None, storage, args, console) == 0
    assert [r["verstr"] for r in json.loads(console.stdout)["runs"]] == [a, b]

    bundles = [(storage.load_metadata(APP, v), {}, load_log(storage, APP, v)) for v in (a, b)]
    monkeypatch.setattr(experiment, "_resolve_experiment_bundles", lambda *a, **k: bundles)
    console = FakeConsole()
    args = argparse.Namespace(name=APP, version=[a, b], tool=None)
    assert experiment.experiment_diff(None, None, storage, args, console) == 1  # no code
    lines = console.stdout.splitlines()
    assert lines[:2] == [f"Comparing {a} -> {b}", ""]
    assert lines[2] == "params: lr 0.1 -> 0.2"
    assert lines[3].startswith("metrics: loss 0.5 -> 0.4")
    assert lines[4:] == [""]
    assert capsys.readouterr().out == ""


def test_run_prints_only_the_verstr_on_stdout(monkeypatch):
    io = IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses({}),
            random=FakeRandom(), host=FakeHost(), console=FakeConsole())
    args = argparse.Namespace(capture_output=False, kill_grace_sec=None, system_metrics=False)
    sup = _Supervision(EmptyStorage(), APP, verstr(1), args, cwd="/work",
                       wait=lambda _sec: False, io=io)
    monkeypatch.setattr(sup, "_start", lambda cmd: object())
    monkeypatch.setattr(sup, "_supervise", lambda proc, cmd: None)
    monkeypatch.setattr(sup, "_stop", lambda proc: None)
    monkeypatch.setattr(sup, "_finish", lambda proc, cmd: 0)
    assert sup.run(["train"]) == 0
    assert io.console.stdout == f"{verstr(1)}\n"


@pytest.mark.parametrize("patch, truncated_at, expected", [
    ("diff --git a/f b/f\n+x\n", None, "\n=== working_tree ===\ndiff --git a/f b/f\n+x\n"),
    ("diff --git a/f b/f\n+x\n" * 4, 30,
     "\n=== working_tree ===\ndiff --gi\n[patch truncated at 30 bytes; raise --max-bytes"
     " to see more]\n"),
])
def test_patch_text_keeps_its_newlines(patch, truncated_at, expected):
    console = FakeConsole()
    meta = {"verstr": "v", "has_untracked_files": False}
    print_patch("v", meta, {"working_tree": patch}, truncated_at or 1 << 20,
                out=console.out, err=console.err)
    assert console.stdout == expected
