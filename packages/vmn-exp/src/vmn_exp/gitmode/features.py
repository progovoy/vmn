"""Run features in a git checkout: what a run's tree says about it.

``capture_features`` builds the ``features`` entry :func:`record_run
<vmn_exp.gitmode.checkout.record_run>` writes next to every git-mode run's
create entry (CLI create/run/sweep, SDK): the files, ``path::name`` functions
and commit subjects of the captured patches (working tree diff, local commits,
deps under their configured path), the main repo's untracked paths (as the
capture listed them), and the author — git config's email in the repo (given
up on after ``GIT_CONFIG_TIMEOUT_SEC``: this runs under the repo lock), else
``VMN_EXP_AUTHOR``, else the first local commit's ``From:``. vmn's own
bookkeeping commits (init, stamp: authored as ``VMN_USER_NAME``; an SDK cold
start leaves them unpushed) are not the run's: this module's
``features_from_patches`` (core's, for a run's patches) skips them.
``features_for_working_tree`` gives the same facts without creating a run;
``rerun_features`` a rerun's, from the original, with the rerunner alone as
the author.

Best-effort, like env capture: a failure is a warning and no entry.
"""
from version_stamp.api import (
    VMN_LOGGER,
    VMN_USER_NAME,
    _list_tarball_members,
    _untracked_candidates,
)
from vmn_exp.core import features as core_features
from vmn_exp.core.features import (
    FEATURES_VERSION,
    author_from_commits,
    build_features_entry,
    code_facts,
)
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.core.identity import env_author, run_author
from vmn_exp.gitmode import capture
from vmn_exp.storage.files import safe_dep_name

_TEXT_PATCHES = ("working_tree", "local_commits")


def features_from_patches(patch_texts) -> dict:
    """Core's ``features_from_patches`` of a run's patches, minus vmn's commits."""
    return core_features.features_from_patches(patch_texts, skip_authors=(VMN_USER_NAME,))


def capture_features(vcs, captured):
    """The ``features`` entry of *captured* (a run's tree), or None."""
    return _best_effort(_tree_entry, vcs, captured)


def features_for_working_tree(vcs, captured=None) -> dict:
    """The working tree's features, shaped like ``IndexSnapshot.features_of``'s;
    ``{}`` when the tree can't be captured. Pass *captured* to reuse a capture."""
    if captured is None:
        captured, err = capture.capture_snapshot(vcs)
        if err is not None:
            return {}
    entry = capture_features(vcs, captured) or {}
    entry.pop("type", None)
    return entry


def rerun_features(vcs, log, metadata, patches):
    """A rerun's ``features`` entry, or None: the original's facts when *log*
    has them at the current version, else its code's (*patches*, the stored
    code object), with the rerunner as the author."""
    return _best_effort(_rerun_entry, vcs, log, metadata, patches or {})


def _best_effort(build, *args):
    try:
        return build(*args)
    except Exception as exc:
        VMN_LOGGER.warning(f"Could not capture features (changed files, commits, "
                           f"author): {exc}")
        VMN_LOGGER.debug("Features capture failed", exc_info=True)
        return None


def _tree_entry(vcs, captured):
    identity = captured.identity
    parsed = features_from_patches(_patch_texts(identity, identity.get("deps") or {}))
    changed = dict(parsed["changed"], untracked=_untracked_paths(vcs, captured))
    return build_features_entry("capture", author=_author(vcs, parsed),
                                **dict(parsed, changed=changed))


def _rerun_entry(vcs, log, metadata, patches):
    original = fold_features(fold_log(log))
    if original and original.get("features_version") == FEATURES_VERSION:
        facts = code_facts(original)
    else:
        parsed = features_from_patches(_patch_texts(patches, _stored_deps(metadata, patches)))
        untracked = _tarball_paths(patches.get("untracked_files"))
        facts = dict(parsed, changed=dict(parsed["changed"], untracked=untracked))
    # The rerunner's identity only: the original's committer did not rerun it.
    author = run_author(vcs.backend.repo_path, [env_author()])
    return build_features_entry("rerun", author=author, **facts)


def _patch_texts(patches, deps):
    """The text patches of *patches* and of *deps* (``{path: patches}``)."""
    texts = [patches.get(key) for key in _TEXT_PATCHES]
    for path, dep in sorted(deps.items()):
        texts.extend((path, dep.get(key)) for key in _TEXT_PATCHES)
    return texts


def _stored_deps(metadata, patches):
    """A stored code object's deps (keyed by safe name) under their dep path."""
    paths = {safe_dep_name(path): path for path in metadata.get("dep_base_commits") or {}}
    return {paths.get(name, name): dep for name, dep in (patches.get("deps") or {}).items()}


def _author(vcs, parsed):
    commit = author_from_commits(parsed["commit_authors"]) or {}
    return run_author(vcs.backend.repo_path,
                      [env_author(), ("commit", commit.get("git_user_email"))])


def _untracked_paths(vcs, captured):
    """The paths the capture hashed; the tree is walked only for a capture
    that did not keep them."""
    if not captured.identity.get("untracked_hash"):
        return []
    listed = getattr(captured, "untracked_paths", None)
    if listed is None:
        listed = [rel for rel, _, _ in _untracked_candidates(vcs.backend.repo_path)]
    return sorted(listed)


def _tarball_paths(tarball):
    return _list_tarball_members(tarball) if tarball else []
