"""release_exp.sh stamps and ships vmn-exp + vmn-exp-sdk (vmn is released on its own)."""
import os
import stat
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GIT = """#!/bin/sh
case "$*" in
  "status --porcelain") [ -n "$DIRTY" ] && echo " M file" ;;
  "tag -l vmn_*") echo vmn_0.10.2 ;;
  "tag -l vmn_exp_*") [ -n "$EXP_TAGGED" ] && echo vmn_exp_0.1.0 ;;
esac
exit 0
"""
LOGGER = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
"""


def _release(tmp_path, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("git", GIT), ("vmn", LOGGER), ("make", LOGGER)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    proc = subprocess.run(
        ["bash", os.path.join(ROOT, "release_exp.sh")], capture_output=True, text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log),
             **env},
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_releases_only_the_exp_packages_with_patch(tmp_path):
    proc, calls = _release(tmp_path, EXP_TAGGED="1")
    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "vmn stamp -r patch vmn_exp",
        "make _build NAME=vmn_exp",
        "make upload NAME=vmn_exp",
    ]


def test_the_first_vmn_exp_release_is_minor(tmp_path):
    # 0.0.1 of vmn-exp/vmn-exp-sdk is taken on PyPI by the name placeholders.
    _, calls = _release(tmp_path)
    assert "vmn stamp -r minor vmn_exp" in calls


def test_refuses_a_dirty_tree(tmp_path):
    proc, calls = _release(tmp_path, DIRTY="1", EXP_TAGGED="1")
    assert proc.returncode != 0
    assert calls == []
