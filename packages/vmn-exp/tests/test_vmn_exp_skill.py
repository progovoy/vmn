"""`vmn-exp skill` carries the experiment guidance that `vmn skill` no longer does."""
import os
import subprocess

import pytest

from exp_helpers import _PY, _SRC_PATH

from version_stamp.cli.entry import vmn_run
from version_stamp.cli.skill import BEGIN_MARKER as VMN_BEGIN
from version_stamp.cli.skill import END_MARKER as VMN_END
from version_stamp.core.logging import init_stamp_logger
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.cli.skill import BEGIN_MARKER, END_MARKER

EXP_MARKER = "vmn-exp run"
CLAUDE_PATH = (".claude", "skills", "vmn-exp", "SKILL.md")


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def _skill(*argv):
    return vmn_exp_run(["skill", *argv])[0]


def _project(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


def test_vmn_exp_skill_explains_how_to_drive_the_ui_fleet_columns(capfd):
    # Moved from tests/test_skill.py: this guidance now lives in `vmn-exp skill`.
    assert _skill() == 0
    out = capfd.readouterr().out
    assert "total / waiting / running / done / failed" in out
    assert "--parent" in out
    assert "start_run(" in out and "run_id=" in out
    assert "docs/vmn-exp/ai-fleet-tracking.md" in out


def test_vmn_exp_skill_covers_experiments_and_model_registry(capfd):
    assert _skill() == 0
    out = capfd.readouterr().out
    assert EXP_MARKER in out
    assert "vmn-exp model register" in out
    assert "vmn stamp -r" not in out


def test_vmn_exp_skill_runs_as_a_command(tmp_path):
    env = {**os.environ, "PYTHONPATH": _SRC_PATH}
    proc = subprocess.run(
        [_PY, "-m", "vmn_exp.cli", "skill"], cwd=tmp_path, env=env,
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert EXP_MARKER in proc.stdout


def test_vmn_exp_skill_markers_differ_from_vmn():
    assert {BEGIN_MARKER, END_MARKER}.isdisjoint({VMN_BEGIN, VMN_END})
    assert VMN_BEGIN not in BEGIN_MARKER and VMN_END not in END_MARKER


def test_install_claude_writes_vmn_exp_skill(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    assert _skill("--install", "--target", "claude") == 0
    content = tmp_path.joinpath(*CLAUDE_PATH).read_text()
    assert content.startswith("---\nname: vmn-exp\n")
    assert "description:" in content
    assert EXP_MARKER in content
    assert not (tmp_path / ".claude" / "skills" / "vmn").exists()


def test_install_defaults_to_claude(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    assert _skill("--install") == 0
    assert tmp_path.joinpath(*CLAUDE_PATH).exists()


def test_install_claude_refuses_overwrite_without_force(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    path = tmp_path.joinpath(*CLAUDE_PATH)
    os.makedirs(path.parent)
    path.write_text("CUSTOM")
    assert _skill("--install") != 0
    assert path.read_text() == "CUSTOM"


def test_install_claude_force_overwrites(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    path = tmp_path.joinpath(*CLAUDE_PATH)
    os.makedirs(path.parent)
    path.write_text("CUSTOM")
    assert _skill("--install", "--force") == 0
    content = path.read_text()
    assert "CUSTOM" not in content
    assert EXP_MARKER in content


def test_install_agents_keeps_vmn_block_intact(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    path = tmp_path / "AGENTS.md"
    path.write_text("# My rules\n")
    assert vmn_run(["skill", "--install", "--target", "agents"])[0] == 0
    with_vmn = path.read_text()
    vmn_block = with_vmn[with_vmn.index(VMN_BEGIN):]

    for _ in range(2):
        assert _skill("--install", "--target", "agents") == 0
    content = path.read_text()
    assert content.startswith("# My rules\n")
    assert vmn_block.rstrip("\n") in content
    assert content.count(BEGIN_MARKER) == 1 and content.count(END_MARKER) == 1
    assert content.count(VMN_BEGIN) == 1 and content.count(VMN_END) == 1
    exp_block = content[content.index(BEGIN_MARKER):]
    assert EXP_MARKER in exp_block and "vmn stamp -r" not in exp_block

    assert vmn_run(["skill", "--install", "--target", "agents"])[0] == 0
    assert path.read_text() == content


def test_install_cursor_creates_when_absent(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    assert _skill("--install", "--target", "cursor") == 0
    assert EXP_MARKER in (tmp_path / ".cursorrules").read_text()


def test_skill_rejects_unknown_target():
    with pytest.raises(SystemExit) as exc:
        _skill("--install", "--target", "vim")
    assert exc.value.code != 0
