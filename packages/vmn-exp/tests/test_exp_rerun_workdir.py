"""The rerun workspace: the original run's code restored in throwaway worktrees.

Plain git repos (no docker): an app repo and a dep repo beside it, each cloned
from a bare remote, recorded the way a run's metadata records them.
"""
import os
import signal
import subprocess
import tempfile
from types import SimpleNamespace

import pytest

from version_stamp.core.logging import ensure_logger
from version_stamp.devversion.untracked import _collect_untracked_tarball
from vmn_exp.cli import rerun_workdir
from vmn_exp.cli.rerun_workdir import exit_on_termination, plan_workdir, prepare_workdir


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo, name, content, message="change"):
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo_with_remote(tmp_path, name):
    remote = tmp_path / "remotes" / f"{name}.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    checkout = tmp_path / "ws" / name
    _git(tmp_path, "clone", "-q", str(remote), str(checkout))
    _commit(checkout, "a.txt", f"{name} base\n", "base")
    _git(checkout, "push", "-q", "origin", "HEAD")
    return checkout, remote


@pytest.fixture
def ws(tmp_path, monkeypatch):
    ensure_logger()
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "tester")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "tester@example.com")
    app, app_remote = _repo_with_remote(tmp_path, "app")
    dep, dep_remote = _repo_with_remote(tmp_path, "repo1")
    return SimpleNamespace(
        tmp=tmp_path, app=app, app_remote=app_remote, dep=dep, dep_remote=dep_remote,
        vcs=SimpleNamespace(vmn_root_path=str(app), name="app"),
    )


def _metadata(ws, with_dep=True):
    base = _git(ws.app, "rev-parse", "HEAD")
    changesets = {".": {"hash": base, "remote": str(ws.app_remote)}}
    if with_dep:
        changesets["../repo1"] = {
            "hash": _git(ws.dep, "rev-parse", "HEAD"), "remote": str(ws.dep_remote),
        }
    return {"app_name": "app", "base_commit": base, "remote": str(ws.app_remote),
            "changesets": changesets}


def _capture_dirty(repo):
    """Dirty *repo* (local commit, edit, untracked file), capture its patches
    and put it back at its base — the live tree no longer has that code."""
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "b.txt", "local commit\n")
    local_commits = _git(repo, "format-patch", "--stdout", f"{base}..HEAD") + "\n"
    (repo / "a.txt").write_text("edited\n")
    working_tree = _git(repo, "diff", "HEAD") + "\n"
    (repo / "new.txt").write_text("untracked\n")
    tarball, _ = _collect_untracked_tarball(str(repo))
    _git(repo, "reset", "-q", "--hard", base)
    _git(repo, "clean", "-qfd")
    return {"local_commits": local_commits, "working_tree": working_tree,
            "untracked_files": tarball}


def _worktrees(repo):
    lines = _git(repo, "worktree", "list", "--porcelain").splitlines()
    return [os.path.realpath(line.split(" ", 1)[1]) for line in lines
            if line.startswith("worktree ")]


def _prepare(ws, metadata, patches, parent=None):
    parent = str(ws.tmp / "out") if parent is None else parent
    workdir, err = prepare_workdir(ws.vcs, metadata, patches, parent)
    assert err is None, err
    return workdir


def test_prepare_creates_detached_worktree_at_base_commit_with_patches_and_untracked(ws):
    metadata = _metadata(ws, with_dep=False)
    workdir = _prepare(ws, metadata, _capture_dirty(ws.app))
    root = workdir.app_root

    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert _git(root, "rev-parse", "HEAD~1") == metadata["base_commit"]
    assert open(os.path.join(root, "b.txt")).read() == "local commit\n"
    assert open(os.path.join(root, "a.txt")).read() == "edited\n"
    assert open(os.path.join(root, "new.txt")).read() == "untracked\n"
    assert os.path.realpath(root) in _worktrees(ws.app)
    assert (ws.app / "a.txt").read_text() == "app base\n"
    assert not (ws.app / "new.txt").exists()


def test_prepare_layout_places_deps_beside_app(ws):
    workdir = _prepare(ws, _metadata(ws), {})

    assert workdir.app_root == os.path.join(workdir.root, "app")
    assert os.path.isfile(os.path.join(workdir.root, "repo1", "a.txt"))
    assert os.path.realpath(os.path.join(workdir.root, "repo1")) in _worktrees(ws.dep)


def test_prepare_dep_at_recorded_hash_with_dep_patch(ws):
    metadata = _metadata(ws)
    recorded = metadata["changesets"]["../repo1"]["hash"]
    (ws.dep / "a.txt").write_text("dep edited\n")
    dep_patch = {"working_tree": _git(ws.dep, "diff", "HEAD") + "\n"}
    _git(ws.dep, "checkout", "-q", "--", "a.txt")
    _commit(ws.dep, "later.txt", "after the run\n")

    workdir = _prepare(ws, metadata, {"deps": {"../repo1": dep_patch}})
    dep_root = os.path.join(workdir.root, "repo1")

    assert _git(dep_root, "rev-parse", "HEAD") == recorded
    assert open(os.path.join(dep_root, "a.txt")).read() == "dep edited\n"
    assert not os.path.exists(os.path.join(dep_root, "later.txt"))


def test_prepare_falls_back_to_clone_when_commit_missing_locally(ws):
    other = ws.tmp / "other"
    _git(ws.tmp, "clone", "-q", str(ws.app_remote), str(other))
    pushed = _commit(other, "remote_only.txt", "only on the remote\n")
    _git(other, "push", "-q", "origin", "HEAD")
    metadata = dict(_metadata(ws, with_dep=False), base_commit=pushed)

    workdir = _prepare(ws, metadata, {})

    assert _git(workdir.app_root, "rev-parse", "HEAD") == pushed
    assert os.path.isfile(os.path.join(workdir.app_root, "remote_only.txt"))
    assert os.path.realpath(workdir.app_root) not in _worktrees(ws.app)


def test_prepare_patch_failure_is_fatal_and_leaves_nothing(ws):
    out = ws.tmp / "out"

    workdir, err = prepare_workdir(
        ws.vcs, _metadata(ws), {"working_tree": "not a diff\n"}, str(out)
    )

    assert workdir is None
    assert "working_tree" in err
    assert not out.exists()
    assert len(_worktrees(ws.app)) == 1
    assert len(_worktrees(ws.dep)) == 1


def test_missing_dep_is_fatal(ws):
    metadata = _metadata(ws)
    metadata["changesets"]["../gone"] = {"hash": "0" * 40}
    out = ws.tmp / "out"

    workdir, err = prepare_workdir(ws.vcs, metadata, {}, str(out))

    assert workdir is None
    assert "../gone" in err
    assert not out.exists()
    assert len(_worktrees(ws.app)) == 1


def test_cleanup_removes_worktree_registration_and_dir(ws):
    workdir = _prepare(ws, _metadata(ws), _capture_dirty(ws.app))

    workdir.cleanup()

    assert not os.path.exists(workdir.root)
    assert len(_worktrees(ws.app)) == 1
    assert len(_worktrees(ws.dep)) == 1


def test_cleanup_of_given_empty_dir_keeps_the_dir(ws):
    out = ws.tmp / "given"
    out.mkdir()
    workdir = _prepare(ws, _metadata(ws), {}, str(out))

    workdir.cleanup()

    assert out.is_dir() and not os.listdir(out)


def test_default_parent_is_a_fresh_tmp_dir(ws):
    workdir, err = prepare_workdir(ws.vcs, _metadata(ws, with_dep=False), {})

    assert err is None
    assert os.path.basename(workdir.root).startswith("vmn-rerun-app-")
    assert os.path.realpath(workdir.root).startswith(
        os.path.realpath(tempfile.gettempdir())
    )
    workdir.cleanup()
    assert not os.path.exists(workdir.root)


def test_prepare_never_writes_vmn_metadata_yml(ws):
    workdir = _prepare(ws, _metadata(ws), _capture_dirty(ws.app))

    for dirpath, _, files in os.walk(workdir.root):
        assert "vmn_metadata.yml" not in files, dirpath


def test_worktree_dir_inside_repo_rejected(ws):
    workdir, err = prepare_workdir(
        ws.vcs, _metadata(ws), {}, str(ws.app / "inside")
    )

    assert workdir is None and "inside the repository" in err
    assert not (ws.app / "inside").exists()


def test_non_empty_worktree_dir_rejected(ws):
    out = ws.tmp / "busy"
    out.mkdir()
    (out / "keep.txt").write_text("mine\n")

    workdir, err = prepare_workdir(ws.vcs, _metadata(ws), {}, str(out))

    assert workdir is None and "not empty" in err
    assert (out / "keep.txt").read_text() == "mine\n"


def test_code_missing_refused(ws):
    metadata = dict(_metadata(ws), code="x.y", code_missing=True)

    workdir, err = prepare_workdir(ws.vcs, metadata, {}, str(ws.tmp / "out"))

    assert workdir is None and "code" in err
    assert not (ws.tmp / "out").exists()


def test_interrupted_setup_cleans_up_and_reraises(ws, monkeypatch):
    def interrupted(dest, patches):
        raise SystemExit(128 + signal.SIGTERM)

    monkeypatch.setattr(rerun_workdir, "_apply_patches_to_workdir", interrupted)
    out = ws.tmp / "out"

    with pytest.raises(SystemExit):
        prepare_workdir(ws.vcs, _metadata(ws), {}, str(out))

    assert not out.exists()
    assert len(_worktrees(ws.app)) == 1
    assert len(_worktrees(ws.dep)) == 1


def test_exit_on_termination_raises_systemexit_and_restores_handlers():
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}

    with pytest.raises(SystemExit) as exc:
        with exit_on_termination():
            os.kill(os.getpid(), signal.SIGTERM)

    assert exc.value.code == 128 + signal.SIGTERM
    assert {s: signal.getsignal(s) for s in before} == before


def test_plan_workdir_reports_sources_without_touching_disk(ws):
    metadata = _metadata(ws)
    metadata["changesets"]["../repo1"]["hash"] = "f" * 40
    planned = ws.tmp / "planned"

    checkouts, err = plan_workdir(ws.vcs, metadata, {"working_tree": "x"}, str(planned))

    assert err is None
    by_name = {c.name: c for c in checkouts}
    assert by_name["."].dest == os.path.join(str(planned), "app")
    assert by_name["."].local_repo == os.path.realpath(ws.app)
    assert by_name["."].steps == ["working_tree"]
    assert by_name["../repo1"].local_repo is None
    assert by_name["../repo1"].remote == str(ws.dep_remote)
    assert not planned.exists()
    assert len(_worktrees(ws.app)) == 1
