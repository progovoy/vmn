"""The workspace of ``vmn-exp rerun``: a run's code restored, strictly, in
throwaway checkouts beside — never inside — the live repository.

Public API::

    plan_workdir(vcs, metadata, patches, parent_dir=None)
        -> (list[Checkout], err: str | None)
    prepare_workdir(vcs, metadata, patches, parent_dir=None)
        -> (Workdir | None, err: str | None)
    Workdir.cleanup() -> bool
    exit_on_termination()          # context manager

*metadata*/*patches* are what ``storage.load`` returns: a code-store run's
patches are its code object's (``vmn_exp.core.code_store.resolve_code``), a
legacy run's are its own, and a run whose object is gone carries
``code_missing`` and is refused. The recorded ``changesets`` place each dep
at its path relative to the app, as islands do (``island_layout``), so
``../repo1`` resolves inside the workspace. Every checkout is a detached
``git worktree`` of the local repo at the recorded hash, or a clone from the
recorded remote when the commit is not local. Any failure — a dep that can't
be materialized, a patch step that doesn't apply — is fatal and removes
whatever was built: running the wrong code silently is worse than not
running. ``vmn_metadata.yml`` is never written.

*parent_dir* must be missing, or an empty directory outside the repo;
``None`` makes a fresh ``vmn-rerun-<app>-*`` directory in ``$TMPDIR``.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import tempfile
from dataclasses import dataclass, field

from vmn_exp.core.code_store import CODE_MISSING
from version_stamp.api import (
    _apply_patches_to_workdir,
    _clone_at,
    _commit_exists,
    _git_ok,
    _resolve_remote,
    create_dep_worktree,
    island_layout,
    remove_registered_worktree,
)

_PATCH_STEPS = ("local_commits", "working_tree", "untracked_files")
_SETUP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


@dataclass(frozen=True)
class Checkout:
    """One checkout of the workspace: the app (``"."``) or a dep."""

    name: str
    dest: str
    commit: str
    local_repo: str | None  # a worktree of this repo; None → clone *remote*
    remote: str | None
    patches: dict = field(default_factory=dict, repr=False)

    @property
    def steps(self):
        return [step for step in _PATCH_STEPS if self.patches.get(step)]


@dataclass
class Workdir:
    root: str
    app_root: str
    checkouts: list = field(default_factory=list)
    owns_root: bool = True

    def cleanup(self):
        """Remove every checkout (and the root when this created it)."""
        ok = True
        for checkout in reversed(self.checkouts):
            if checkout.local_repo and not remove_registered_worktree(
                checkout.local_repo, checkout.dest
            ):
                ok = False
        if self.owns_root:
            shutil.rmtree(self.root, ignore_errors=True)
        else:
            _empty_dir(self.root)
        return ok


def plan_workdir(vcs, metadata, patches, parent_dir=None):
    """The checkouts :func:`prepare_workdir` would make; touches nothing."""
    err = _refusal(vcs, metadata, parent_dir)
    if err:
        return [], err
    root = os.path.abspath(parent_dir or _default_parent_pattern(vcs, metadata))
    sources = _sources(metadata)
    deps = {name: {"rel_path": name} for name in sources if name != "."}
    layout = island_layout(vcs.vmn_root_path, deps, root)
    checkouts = []
    for name, (commit, remote) in sources.items():
        checkout, err = _plan_checkout(vcs, name, commit, remote, layout[name], patches)
        if err:
            return [], err
        checkouts.append(checkout)
    return sorted(checkouts, key=lambda c: c.dest), None


def prepare_workdir(vcs, metadata, patches, parent_dir=None):
    """``(Workdir, None)`` with the run's code in place, or ``(None, err)``
    after removing everything it built."""
    err = _refusal(vcs, metadata, parent_dir)
    if err:
        return None, err
    workdir = _make_root(vcs, metadata, parent_dir)
    try:
        err = _populate(vcs, metadata, patches, workdir)
    except BaseException:
        workdir.cleanup()
        raise
    if err:
        workdir.cleanup()
        return None, err
    return workdir, None


@contextlib.contextmanager
def exit_on_termination():
    """Turn SIGTERM/SIGHUP into ``SystemExit(128 + N)`` while setting up, so
    ``finally``/cleanup code runs; the previous handlers come back after."""

    def _exit(signum, _frame):
        raise SystemExit(128 + signum)

    previous = {sig: signal.signal(sig, _exit) for sig in _SETUP_SIGNALS}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _refusal(vcs, metadata, parent_dir):
    if metadata.get(CODE_MISSING):
        return f"the code of {metadata.get('verstr')} is missing from the store"
    if not metadata.get("base_commit"):
        return "the run records no base commit"
    if parent_dir:
        return _parent_dir_refusal(vcs, parent_dir)
    return None


def _parent_dir_refusal(vcs, parent_dir):
    repo = os.path.realpath(vcs.vmn_root_path)
    target = os.path.realpath(parent_dir)
    if os.path.commonpath([repo, target]) == repo:
        return f"worktree dir {parent_dir} is inside the repository"
    if os.path.exists(target) and (not os.path.isdir(target) or os.listdir(target)):
        return f"worktree dir {parent_dir} is not empty"
    return None


def _sources(metadata):
    """``{name: (commit, remote)}`` of the app and every recorded dep."""
    sources = {".": (metadata["base_commit"], metadata.get("remote"))}
    for name, info in (metadata.get("changesets") or {}).items():
        if name != ".":
            sources[name] = (info.get("hash"), info.get("remote"))
    return sources


def _plan_checkout(vcs, name, commit, remote, dest, patches):
    if not commit:
        return None, f"dependency {name} records no commit"
    repo = os.path.realpath(os.path.join(vcs.vmn_root_path, name))
    local = repo if _commit_exists(repo, commit) else None
    remote = _resolve_remote(remote, vcs)
    if not local and not remote:
        return None, f"{_label(name)} at {commit[:7]} is not local and has no remote"
    return Checkout(name, dest, commit, local, remote, _patches_of(name, patches)), None


def _patches_of(name, patches):
    if name == ".":
        return patches
    deps = patches.get("deps") or {}
    return deps.get(name) or deps.get(name.replace(os.sep, "_").replace("/", "_")) or {}


def _make_root(vcs, metadata, parent_dir):
    if not parent_dir:
        root = tempfile.mkdtemp(prefix=_default_prefix(vcs, metadata))
        return Workdir(root=root, app_root=root)
    root = os.path.abspath(parent_dir)
    owns_root = not os.path.exists(root)
    os.makedirs(root, exist_ok=True)
    return Workdir(root=root, app_root=root, owns_root=owns_root)


def _populate(vcs, metadata, patches, workdir):
    checkouts, err = plan_workdir(vcs, metadata, patches, workdir.root)
    if err:
        return err
    for repo in {c.local_repo for c in checkouts if c.local_repo}:
        _git_ok(["worktree", "prune"], cwd=repo)
    for checkout in checkouts:
        err = _materialize(checkout, workdir)
        if err:
            return err
        if checkout.name == ".":
            workdir.app_root = checkout.dest
    return None


def _materialize(checkout, workdir):
    if checkout.local_repo:
        failed = create_dep_worktree(
            checkout.local_repo, checkout.dest, {"start_point": checkout.commit}, None
        )
    else:
        failed = _clone_at(checkout.dest, None, checkout.remote, checkout.commit)
    if failed:
        return f"could not check out {_label(checkout.name)} at {checkout.commit[:7]}"
    workdir.checkouts.append(checkout)
    failed_steps = _apply_patches_to_workdir(checkout.dest, checkout.patches)
    if failed_steps:
        return f"could not apply {', '.join(failed_steps)} to {_label(checkout.name)}"
    return None


def _label(name):
    return "the app" if name == "." else f"dependency {name}"


def _default_prefix(vcs, metadata):
    app_name = metadata.get("app_name") or vcs.name
    return f"vmn-rerun-{app_name.replace('/', '-')}-"


def _default_parent_pattern(vcs, metadata):
    return os.path.join(tempfile.gettempdir(), _default_prefix(vcs, metadata) + "*")


def _empty_dir(path):
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if os.path.isdir(full) and not os.path.islink(full):
            shutil.rmtree(full, ignore_errors=True)
        else:
            os.remove(full)
