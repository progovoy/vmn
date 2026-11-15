"""packages/vmn-exp/CHANGELOG.md is git-cliff over vmn_exp_ tags, scoped to the two exp packages.

Real git and the venv's git-cliff: the risk is how git-cliff scopes paths and
orders these tags, which only the real tool can say. The flags match the
Makefile's `_changelog` target.
"""
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
INCLUDE_PATHS = ("packages/vmn-exp/**", "packages/vmn-exp-sdk/**")


def _git_cliff():
    return (shutil.which("git-cliff", path=os.path.dirname(sys.executable))
            or shutil.which("git-cliff"))


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def _commit(repo, path, subject):
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(subject)
    _git(repo, "add", path)
    _git(repo, "commit", "-m", subject)


def _tag(repo, name):
    _git(repo, "tag", "-a", name, "-m", name)


def _history(repo):
    _git(repo, "init", "-q", "-b", "master")
    _commit(repo, "packages/vmn-exp/a.py", "feat(exp): before the init tag")
    _tag(repo, "vmn_exp_0.0.0")
    _commit(repo, "packages/vmn-exp/b.py", "feat(exp): first exp feature")
    _tag(repo, "vmn_exp_0.1.0")
    _commit(repo, "packages/vmn/c.py", "fix(core): a core only fix")
    _tag(repo, "vmn_0.10.2")
    _commit(repo, "docs/d.md", "feat(docs): a docs only feature")
    _commit(repo, "packages/vmn-exp-sdk/e.py", "fix(sdk)!: a breaking sdk change")
    _commit(repo, "packages/vmn-exp/f.py", "perf(exp-ui): a faster board")
    _commit(repo, "packages/vmn-exp/g.py", "test(exp): a test only change")
    _tag(repo, "vmn_exp_0.1.1")


def _changelog(repo):
    cliff = _git_cliff()
    assert cliff, "git-cliff is installed with the test requirements"
    include = [arg for path in INCLUDE_PATHS for arg in ("--include-path", path)]
    result = subprocess.run(
        [cliff, "--config", str(ROOT / "packages/vmn-exp/cliff.toml"), *include],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return result.stdout


def test_only_commits_under_the_exp_packages_between_exp_tags_are_listed(tmp_path):
    _history(tmp_path)
    text = _changelog(tmp_path)

    for absent in ("core only fix", "docs only feature", "before the init tag",
                   "test only change", "0.10.2", "0.0.0"):
        assert absent not in text
    newer, older = text.index("## 0.1.1"), text.index("## 0.1.0")
    assert newer < older
    release = text[newer:older]
    assert release.index("Behaviour changes") < release.index("a breaking sdk change")
    assert release.index("a breaking sdk change") < release.index("a faster board")
    assert "first exp feature" in text[older:]
    assert "upgrading.md" in text[:newer]
