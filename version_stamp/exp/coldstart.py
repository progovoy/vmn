#!/usr/bin/env python3
"""Auto-initialize vmn for ``start_run`` in a fresh repo — locally only.

``vmn exp create``/``run`` init the repo and stamp a ``0.0.0`` baseline on first
use; the SDK does the same through the very same CLI helpers. Unlike the CLI it
never pushes: a training script must not publish commits and tags as a side
effect (and must not crash in a checkout that has no remote at all). The
baseline commit and tag stay local until the user pushes them
(``git push --follow-tags``) or the next ``vmn stamp`` does.
"""
import contextlib
import os
from types import SimpleNamespace

from version_stamp.cli.constants import INIT_FILENAME
from version_stamp.core.constants import VMN_BE_TYPE_GIT
from version_stamp.core.experiment_writer import get_repo_lock
from version_stamp.core.utils import resolve_root_path

# The repo state `vmn exp create` demands, and what it tolerates — the SDK
# cold-starts on exactly the same terms.
_EXPECTED_STATUS = {"repo_tracked", "app_tracked"}
_OPTIONAL_STATUS = {
    "repos_exist_locally",
    "detached",
    "pending",
    "outgoing",
    "version_not_matched",
    "dirty_deps",
    "deps_synced_with_conf",
}
_DIRTY_OK = {"pending", "outgoing"}
_PUSHING_METHODS = ("push",)


def build_vcs(app_name):
    from version_stamp.stamping.publisher import VersionControlStamper

    return VersionControlStamper(
        {
            "root": False,
            "name": app_name,
            "root_path": resolve_root_path(),
            "be_type": VMN_BE_TYPE_GIT,
        }
    )


def tracked_vcs(app_name, root_path):
    """``(vcs, status)`` for *app_name*, cold-starting the repo/app if needed.

    *status* is the repo status the check computed, for the caller to reuse, or
    None after a cold start (the repo changed since).

    The check runs without the repo lock; only an actual init takes it. The vcs
    is then rebuilt under the lock — one built before it would miss an init
    another worker finished while this one waited — and re-checked there.
    """
    vcs = build_vcs(app_name)
    status = repo_status(vcs)
    if not status.error:
        return vcs, status
    with get_repo_lock(root_path):
        vcs = build_vcs(app_name)
        cold_start(vcs, repo_status(vcs))
    return vcs, None


def repo_status(vcs):
    """The repo status `vmn exp create` checks, untracked repo/app included."""
    from version_stamp.cli.commands import _get_repo_status

    # An untracked repo or app is the cold-start case this module exists to
    # handle, so it must not be announced as an error first — that made a
    # successful first run look like a crash.
    return _get_repo_status(
        vcs,
        _EXPECTED_STATUS,
        _OPTIONAL_STATUS,
        suppress_errors={"repo_tracked", "app_tracked"},
    )


def cold_start(vcs, status):
    """Init vmn tracking and a 0.0.0 baseline for *vcs*, as ``vmn exp`` does."""
    from version_stamp.cli.commands import _init_app, handle_init

    if not status.error:
        return

    be = vcs.backend
    vmn_init_file = os.path.join(vcs.vmn_root_path, ".vmn", INIT_FILENAME)

    def missing(state, path):
        return state not in status.state and not be.is_path_tracked(path)

    init_repo = missing("repo_tracked", vmn_init_file)
    init_app = missing("app_tracked", vcs.app_dir_path)
    with local_only(be):
        # handle_init only ever reads vmn_ctx.vcs, so there is no argparse
        # namespace to fabricate.
        if init_repo and handle_init(SimpleNamespace(vcs=vcs), extra_optional=_DIRTY_OK):
            raise RuntimeError(_failure(vcs.name, "initialize the repo"))
        if init_app and _init_app(vcs, "0.0.0", extra_optional=_DIRTY_OK):
            raise RuntimeError(_failure(vcs.name, "stamp a baseline"))

    if init_repo or init_app:
        vcs.update_attrs_from_app_conf_file()
        vcs.initialize_backend_attrs()


@contextlib.contextmanager
def local_only(backend):
    """Make *backend* commit and tag without ever touching a remote.

    Shadows the pushing methods on this one instance (the class, and every other
    backend, are untouched). With nothing pushed, the post-publish "outgoing
    changes" check would fire by design, so it is silenced too.
    """
    overrides = {name: _skip_push for name in _PUSHING_METHODS}
    overrides["check_for_outgoing_changes"] = lambda: None
    for name, override in overrides.items():
        setattr(backend, name, override)
    try:
        yield backend
    finally:
        for name in overrides:
            backend.__dict__.pop(name, None)


def _skip_push(*args, **kwargs):
    return None


def _failure(app_name, what):
    return (
        f"Could not {what} for '{app_name}' automatically. "
        f"Run 'vmn stamp -r patch {app_name}' once, then start the run again."
    )
