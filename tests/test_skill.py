import os

import pytest

from version_stamp.cli.entry import vmn_run
from version_stamp.cli.skill import END_MARKER, install_skill, BEGIN_MARKER
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
    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    ret = vmn_run(["skill", "--install"])[0]
    assert ret == 0
    assert (tmp_path / ".claude" / "skills" / "vmn" / "SKILL.md").exists()


def test_skill_install_via_cli_resolves_project_root_from_nested_cwd(
    tmp_path, monkeypatch
):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "package"
    nested.mkdir(parents=True)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.chdir(nested)

    ret = vmn_run(["skill", "--install", "--target", "agents"])[0]

    assert ret == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert not (nested / "AGENTS.md").exists()


def test_skill_install_via_cli_resolves_vmn_working_dir(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    (project / ".vmn").mkdir(parents=True)
    nested = project / "src" / "package"
    nested.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("VMN_WORKING_DIR", str(nested))

    ret = vmn_run(["skill", "--install", "--target", "cursor"])[0]

    assert ret == 0
    assert (project / ".cursorrules").exists()
    assert not (nested / ".cursorrules").exists()


def test_skill_install_via_cli_rejects_unmanaged_directory(
    tmp_path, monkeypatch, capfd
):
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    ret = vmn_run(["skill", "--install"])[0]

    assert ret == 1
    assert not (tmp_path / ".claude").exists()
    assert "unmanaged directory" in capfd.readouterr().err.lower()


@pytest.mark.parametrize(
    "content",
    [
        f"user before\n{BEGIN_MARKER}\nuser after\n",
        f"user before\n{END_MARKER}\nuser after\n",
        f"{END_MARKER}\nuser content\n{BEGIN_MARKER}\n",
        f"{BEGIN_MARKER}\nold\n{END_MARKER}\n{BEGIN_MARKER}\nuser content\n",
        f"{BEGIN_MARKER}\n{END_MARKER}\nuser content\n{END_MARKER}\n",
    ],
)
def test_install_agents_rejects_malformed_markers_without_changing_file(
    tmp_path, content, caplog
):
    path = tmp_path / "AGENTS.md"
    path.write_text(content)

    ret = install_skill("agents", root=str(tmp_path))

    assert ret == 1
    assert path.read_text() == content
    assert "marker" in caplog.text.lower()


def test_install_agents_preserves_original_when_atomic_replace_fails(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "AGENTS.md"
    original = "# User instructions\n"
    path.write_text(original)

    def fail_replace(source, destination):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(os, "replace", fail_replace)

    ret = install_skill("agents", root=str(tmp_path))

    assert ret == 1
    assert path.read_text() == original
    assert list(tmp_path.iterdir()) == [path]
    assert "failed to install" in caplog.text.lower()


def test_install_skill_rejects_non_directory_root(tmp_path, caplog):
    root = tmp_path / "not-a-directory"
    root.write_text("content")

    ret = install_skill("agents", root=str(root))

    assert ret == 1
    assert root.read_text() == "content"
    assert "not a directory" in caplog.text.lower()
