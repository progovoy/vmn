"""GET .../workspaces/{ws}/git: branch, HEAD and dirty for the shell's
context root, from one lock-free git process (plan 19 §2.1)."""
import os
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.ui import git_context  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _repo(tmp_path, name="repo", commit=True):
    path = tmp_path / name
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    if commit:
        (path / "a.txt").write_text("a\n")
        _git(path, "add", "a.txt")
        _git(path, "commit", "-q", "-m", "init")
    return path


def _head(path):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True)
    return out.stdout.strip()


def _client(tmp_path, paths, stores=()):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui"))
    for name, path in paths.items():
        manager.attach_path(name, str(path))
    for name in stores:
        manager.add_store(name, f"file://{tmp_path}/{name}-store")
    return TestClient(create_app(manager))


def _context(client, ws="ws"):
    r = client.get(f"/api/v1/workspaces/{ws}/git")
    assert r.status_code == 200, r.text
    return r.json()


def test_clean_branch(tmp_path):
    repo = _repo(tmp_path)
    head = _head(repo)
    assert _context(_client(tmp_path, {"ws": repo})) == {
        "branch": "main", "detached": False, "head": head,
        "head_short": head[:7], "dirty": False, "store": os.path.join(".vmn", "store"),
    }


def test_tracked_edit_is_dirty(tmp_path):
    repo = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n")
    assert _context(_client(tmp_path, {"ws": repo}))["dirty"] is True


def test_untracked_only_is_clean(tmp_path):
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("x\n")
    assert _context(_client(tmp_path, {"ws": repo}))["dirty"] is False


def test_detached_head(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach")
    body = _context(_client(tmp_path, {"ws": repo}))
    assert body["branch"] is None
    assert body["detached"] is True
    assert body["head"] == _head(repo)


def test_repo_without_commits(tmp_path):
    repo = _repo(tmp_path, commit=False)
    body = _context(_client(tmp_path, {"ws": repo}))
    assert body["branch"] == "main"
    assert body["head"] is None and body["head_short"] is None
    assert body["dirty"] is False


def test_a_non_utf8_branch_name_still_answers(tmp_path):
    repo = _repo(tmp_path, commit=False)
    (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/caf\xe9\n")
    body = _context(_client(tmp_path, {"ws": repo}))
    assert body["branch"] == "caf\ufffd"
    assert body["dirty"] is False


def test_not_a_repo_answers_200_with_an_error(tmp_path):
    path = tmp_path / "plain"
    os.makedirs(path / ".vmn")
    body = _context(_client(tmp_path, {"ws": path}))
    assert body["branch"] is None and body["head"] is None
    assert body["dirty"] is None and body["detached"] is False
    assert body["store"] == os.path.join(".vmn", "store")
    assert body["error"]


def test_timeout_answers_200_with_timeout(tmp_path, monkeypatch):
    repo = _repo(tmp_path)

    def _slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

    monkeypatch.setattr(git_context.subprocess, "run", _slow)
    assert _context(_client(tmp_path, {"ws": repo}))["error"] == "timeout"


def test_store_workspace_is_400(tmp_path):
    client = _client(tmp_path, {}, stores=["team"])
    assert client.get("/api/v1/workspaces/team/git").status_code == 400


def test_unknown_workspace_is_404(tmp_path):
    client = _client(tmp_path, {})
    assert client.get("/api/v1/workspaces/nope/git").status_code == 404


def _counting(monkeypatch):
    calls = []
    real = subprocess.run

    def _run(argv, **kwargs):
        calls.append((argv, kwargs))
        return real(argv, **kwargs)

    monkeypatch.setattr(git_context.subprocess, "run", _run)
    return calls


def test_one_lock_free_git_process(tmp_path, monkeypatch):
    client = _client(tmp_path, {"ws": _repo(tmp_path)})
    calls = _counting(monkeypatch)
    _context(client)
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:2] == ["git", "--no-optional-locks"]
    assert "--untracked-files=no" in argv
    assert kwargs["timeout"] == 2


def test_memoized_for_a_few_seconds(tmp_path, monkeypatch):
    client = _client(tmp_path, {"ws": _repo(tmp_path)})
    calls = _counting(monkeypatch)
    _context(client)
    _context(client)
    assert len(calls) == 1


def test_removing_the_workspace_forgets_it(tmp_path, monkeypatch):
    first, second = _repo(tmp_path, "first"), _repo(tmp_path, "second")
    _git(second, "checkout", "-q", "-b", "other")
    client = _client(tmp_path, {"ws": first})
    assert _context(client)["branch"] == "main"
    assert client.delete("/api/v1/workspaces/ws").status_code == 204
    r = client.post("/api/v1/workspaces", json={"name": "ws", "path": str(second)},
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 201, r.text
    assert _context(client)["branch"] == "other"
