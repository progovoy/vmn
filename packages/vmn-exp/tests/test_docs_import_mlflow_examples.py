"""Every documented ``vmn-exp import-mlflow`` command works as written. The
exp parser's positionals are ``action name refs*``, so an app named after the
flags is rejected (``unrecognized arguments`` on Python 3.9, parsed as
``create import-mlflow`` on 3.12+): the docs name the app right after the
action, and their ``--mlruns ./mlruns`` examples run against a fake FileStore.
"""
import glob
import os
import re
import shlex

import pytest
from exp_helpers import _PROJECT_ROOT
from mlflow_fixtures import MlflowFixtureBuilder
from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli.main import vmn_exp_run

APP = "my_app"
COMMAND = "vmn-exp import-mlflow"
STORE_ENVS = ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
              "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXP_OFFLINE", "VMN_WORKING_DIR")


def _doc_paths():
    return sorted(glob.glob(os.path.join(_PROJECT_ROOT, "docs", "vmn-exp", "*.md")))


def _sh_lines(path):
    """The command lines of *path*'s ``sh`` blocks, continuations joined."""
    lines, fenced, pending = [], False, ""
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("```"):
                fenced = not fenced and line == "```sh"
                continue
            if not fenced:
                continue
            line = pending + line
            pending = line[:-1] + " " if line.endswith("\\") else ""
            if not pending:
                lines.append(line)
    return lines


def _documented_imports():
    """``(doc name, argv after "vmn-exp")`` of every documented import."""
    found = []
    for path in _doc_paths():
        for line in _sh_lines(path):
            if line.startswith(COMMAND + " "):
                found.append((os.path.basename(path), shlex.split(line, comments=True)[1:]))
    return found


def _parsed(argv):
    try:
        return parse_user_commands(["exp", *argv])
    except SystemExit:
        pytest.fail(f"vmn-exp {shlex.join(argv)}: the exp parser rejects it")


def test_every_documented_import_mlflow_line_imports_into_the_named_app():
    imports = _documented_imports()
    assert len(imports) >= 10  # migrating-from-mlflow.md and experiments.md
    for doc, argv in imports:
        args = _parsed(argv)
        assert (args.action, args.name, args.refs) == ("import-mlflow", APP, []), (doc, argv)


def test_no_doc_or_synopsis_puts_import_mlflow_flags_before_the_app():
    paths = _doc_paths() + [os.path.join(_PROJECT_ROOT, "CLAUDE.md")]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for after in re.findall(re.escape(COMMAND) + r"[ \t]+(\S+)", text):
            assert after in (APP, "<app>"), (os.path.basename(path), after)


def _fake_mlruns(root):
    builder = MlflowFixtureBuilder(root / "mlruns")
    builder.add_experiment("1", "Baseline")
    builder.add_experiment("3", "my_exp")
    builder.add_run("1", "a" * 32)
    builder.add_run("3", "b" * 32)


def test_the_documented_mlruns_imports_run_against_a_fake_file_store(tmp_path, monkeypatch,
                                                                     capsys):
    for name in STORE_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    _fake_mlruns(tmp_path)
    file_store_lines = [argv for _, argv in _documented_imports() if "./mlruns" in argv]
    assert any("--refresh-features" in argv for argv in file_store_lines)

    for argv in file_store_lines:
        _parsed(argv)
        assert vmn_exp_run(argv)[0] == 0, argv

    assert "imported 2," in capsys.readouterr().out
