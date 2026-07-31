import os

import pytest

from version_stamp.cli.entry import vmn_run
from version_stamp.cli.skill import install_skill, BEGIN_MARKER
from version_stamp.core.logging import init_stamp_logger

# Markers unique to each section of the skill block.
VMN_MARKER = "vmn stamp"
METHODOLOGY_MARKER = "Development gold rules"


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def test_skill_default_excludes_methodology(capfd):
    ret = vmn_run(["skill"])[0]
    assert ret == 0
    out = capfd.readouterr().out
    assert VMN_MARKER in out
    assert METHODOLOGY_MARKER not in out


def test_skill_methodology_flag_includes_it(capfd):
    ret = vmn_run(["skill", "--methodology"])[0]
    assert ret == 0
    out = capfd.readouterr().out
    assert VMN_MARKER in out
    assert METHODOLOGY_MARKER in out


def test_install_claude_creates_skill_file(tmp_path):
    ret = install_skill("claude", root=str(tmp_path))
    assert ret == 0
    p = tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md"
    assert p.exists()
    content = p.read_text()
    assert content.startswith("---\n")
    assert "name: vmn" in content
    assert "description:" in content
    assert VMN_MARKER in content
    assert METHODOLOGY_MARKER not in content


def test_install_claude_methodology(tmp_path):
    install_skill("claude", methodology=True, root=str(tmp_path))
    content = (tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md").read_text()
    assert METHODOLOGY_MARKER in content


def test_install_claude_refuses_overwrite_without_force(tmp_path):
    p = tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md"
    os.makedirs(p.parent)
    p.write_text("CUSTOM")
    ret = install_skill("claude", root=str(tmp_path))
    assert ret != 0
    assert p.read_text() == "CUSTOM"


def test_install_claude_force_overwrites(tmp_path):
    p = tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md"
    os.makedirs(p.parent)
    p.write_text("CUSTOM")
    ret = install_skill("claude", force=True, root=str(tmp_path))
    assert ret == 0
    content = p.read_text()
    assert "CUSTOM" not in content
    assert VMN_MARKER in content


def test_install_agents_upserts_block_idempotently(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# My AGENTS.md\n\nSome existing rules.\n")
    assert install_skill("agents", root=str(tmp_path)) == 0
    once = p.read_text()
    assert "Some existing rules." in once
    assert once.count(BEGIN_MARKER) == 1
    assert VMN_MARKER in once

    assert install_skill("agents", root=str(tmp_path)) == 0
    twice = p.read_text()
    assert twice.count(BEGIN_MARKER) == 1
    assert "Some existing rules." in twice


def test_install_cursor_creates_when_absent(tmp_path):
    assert install_skill("cursor", root=str(tmp_path)) == 0
    p = tmp_path / ".cursorrules"
    assert p.exists()
    assert VMN_MARKER in p.read_text()


def test_skill_install_via_cli_defaults_to_claude(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ret = vmn_run(["skill", "--install"])[0]
    assert ret == 0
    assert (tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md").exists()
