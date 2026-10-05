"""build_dist.sh builds an app's packages at the version `vmn show` reports."""
import os
import shutil
import stat
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# `vmn show` prints a bare version, or a dirty report when HEAD is not stamped.
VMN = """#!/bin/sh
if [ -n "$DIRTY" ]; then
  printf 'dirty:\\n- version_not_matched\\nout: 0.1.4\\n\\n'
else
  echo "$SHOWN"
fi
"""
# Records each package built and the version files as the build saw them.
UV = """#!/bin/sh
pkg=$4
echo "build $pkg" >> "$LOG"
grep -h 'version = \\|vmn-exp-sdk==' "$pkg/pyproject.toml" "$pkg"/src/*/version.py \\
  2>/dev/null >> "$LOG"
[ -z "$UV_FAIL" ]
"""

VMN_FILES = {
    "packages/vmn/pyproject.toml": 'name = "vmn"\nversion = "0.10.2-rc.15"  # stamp\n',
    "packages/vmn/src/version_stamp/version.py": (
        'name = "vmn"\nversion = "0.10.2-rc.15"\n_version = "0.10.2-rc.15"\n'
    ),
}
EXP_FILES = {
    "packages/vmn-exp-sdk/pyproject.toml": 'version = "0.1.3"  # stamp\n',
    "packages/vmn-exp/pyproject.toml": (
        'version = "0.1.3"  # stamp\ndependencies = [\n    "vmn-exp-sdk==0.1.3",\n]\n'
    ),
}


def _build(tmp_path, name, **env):
    shutil.copy(os.path.join(ROOT, "build_dist.sh"), tmp_path)
    for rel, body in {**VMN_FILES, **EXP_FILES}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool, body in (("vmn", VMN), ("uv", UV)):
        (bin_dir / tool).write_text(body)
        (bin_dir / tool).chmod(0o755)
    log = tmp_path / "calls.log"
    script = tmp_path / "build_dist.sh"
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    proc = subprocess.run(
        ["bash", str(script), name, str(tmp_path / "dist")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOG": str(log),
             **env},
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def _unchanged(tmp_path, files):
    return all((tmp_path / rel).read_text() == body for rel, body in files.items())


def test_builds_vmn_at_the_shown_release_version(tmp_path):
    proc, calls = _build(tmp_path, "vmn", SHOWN="0.10.2")
    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "build packages/vmn",
        'version = "0.10.2"  # stamp',
        'version = "0.10.2"',
        '_version = "0.10.2"',
    ]


def test_restores_the_version_files_after_the_build(tmp_path):
    _build(tmp_path, "vmn", SHOWN="0.10.2")
    assert _unchanged(tmp_path, VMN_FILES)


def test_builds_both_exp_packages_with_the_sdk_pin(tmp_path):
    proc, calls = _build(tmp_path, "vmn_exp", SHOWN="0.1.4")
    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "build packages/vmn-exp-sdk",
        'version = "0.1.4"  # stamp',
        "build packages/vmn-exp",
        'version = "0.1.4"  # stamp',
        '    "vmn-exp-sdk==0.1.4",',
    ]
    assert _unchanged(tmp_path, EXP_FILES)


def test_refuses_when_head_is_not_a_stamped_version(tmp_path):
    proc, calls = _build(tmp_path, "vmn_exp", DIRTY="1")
    assert proc.returncode != 0
    assert "vmn_exp" in proc.stderr
    assert calls == []


def test_a_failed_build_still_restores_the_files(tmp_path):
    proc, _ = _build(tmp_path, "vmn", SHOWN="0.10.2", UV_FAIL="1")
    assert proc.returncode != 0
    assert _unchanged(tmp_path, VMN_FILES)
