"""The quickstart in docs/vmn-exp/README.md and its PyPI mirror
packages/vmn-exp/README.md works when pasted: the install line brings the
dashboard it runs, train.py logs the metric the list sorts on, and the page
says what the first run does to git (plan 38 A7)."""
import os
import re
import subprocess

from exp_helpers import _PROJECT_ROOT, _PY, _SRC_PATH, _storage

from vmn_exp.sdk.reader import list_runs

DOCS_README = "docs/vmn-exp/README.md"
PACKAGE_README = "packages/vmn-exp/README.md"
QUICKSTARTS = (DOCS_README, PACKAGE_README)
QUICKSTART_APP = "my_app"

FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.M | re.S)
UI_COMMAND = re.compile(r"^vmn-exp ui\b")
PIP_INSTALL = re.compile(r"^pip install\b")


def fenced_blocks(text, lang=None):
    return [body for found, body in FENCE.findall(text) if lang is None or found == lang]


def command_lines(text):
    lines = []
    for block in fenced_blocks(text, "sh"):
        for line in block.splitlines():
            command = " ".join(line.split("#", 1)[0].split())
            if command:
                lines.append(command)
    return lines


def ui_runs_without_the_extra(text):
    """`vmn-exp ui` lines whose nearest earlier `pip install` lacks [ui]."""
    install = None
    offending = []
    for line in command_lines(text):
        if PIP_INSTALL.match(line):
            install = line
        elif UI_COMMAND.match(line) and (install is None or "[ui]" not in install):
            offending.append(line)
    return offending


def quickstart(text):
    section = text.split("## Quickstart", 1)[1]
    return section.split("\n## ", 1)[0]


def paragraph_with(text, *needles):
    flat = (re.sub(r"\s+", " ", p) for p in text.split("\n\n"))
    return next((p for p in flat if all(n in p for n in needles)), "")


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def test_a_ui_command_after_a_bare_install_is_reported():
    page = "```sh\npip install vmn-exp   # [ui] adds it\nvmn-exp ui\n```\n"
    assert ui_runs_without_the_extra(page) == ["vmn-exp ui"]
    fixed = '```sh\npip install "vmn-exp[ui]"\n```\n\n```sh\nvmn-exp ui  # url\n```\n'
    assert ui_runs_without_the_extra(fixed) == []
    assert ui_runs_without_the_extra("```sh\nvmn-exp ui\n```\n") == ["vmn-exp ui"]


def test_any_block_that_runs_vmn_exp_ui_installs_the_ui_extra():
    for relpath in QUICKSTARTS:
        text = _read(relpath)
        assert any(UI_COMMAND.match(line) for line in command_lines(text)), relpath
        assert ui_runs_without_the_extra(text) == [], relpath


def test_quickstart_names_the_local_baseline_commit_and_tag():
    for relpath in QUICKSTARTS:
        section = quickstart(_read(relpath))
        assert "git commit --allow-empty" in section, relpath
        assert "git identity" in section, relpath
        side_effect = paragraph_with(section, f"`{QUICKSTART_APP}_0.0.0`")
        assert "commits" in side_effect and "nothing is pushed" in side_effect, relpath


def test_quickstart_says_the_cli_first_run_pushes_when_there_is_a_remote():
    for relpath in QUICKSTARTS:
        section = quickstart(_read(relpath))
        wrap = paragraph_with(section, f"vmn-exp run {QUICKSTART_APP} --")
        assert "pushes" in wrap and "remote" in wrap, relpath


def test_package_readme_quickstart_matches_the_docs_quickstart_commands():
    docs = quickstart(_read(DOCS_README))
    package = quickstart(_read(PACKAGE_README))
    assert command_lines(package) == command_lines(docs)
    assert fenced_blocks(package, "python") == fenced_blocks(docs, "python")


def _quickstart_train_py():
    (train_py,) = fenced_blocks(quickstart(_read(DOCS_README)), "python")
    return train_py


def test_the_quickstart_train_py_block_runs_and_records_loss(app_layout):
    script = os.path.join(app_layout.repo_path, "train.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(_quickstart_train_py())
    env = dict(os.environ, VMN_WORKING_DIR=app_layout.repo_path, PYTHONPATH=_SRC_PATH)
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        env.pop(key, None)

    proc = subprocess.run(
        [_PY, script], cwd=app_layout.repo_path, env=env, capture_output=True, text=True
    )

    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    rows = list_runs(QUICKSTART_APP, storage=_storage(app_layout))
    assert len(rows) == 1
    assert rows[0]["status"] == "succeeded"
    assert "loss" in rows[0]["metrics"]
