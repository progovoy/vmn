#!/usr/bin/env python3
"""Read-side changelog: conventional commits between two stamped versions.

A cheap local git read (``git log range``) plus pure grouping — no lock, no
network. Reuses the same conventional-commit grouping the stamper uses.
"""
import os

import git

from version_stamp.core.changelog import group_commits
from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.ui.readers.versions import list_versions


def _row_for(rows, verstr):
    for r in rows:
        if r["verstr"] == verstr:
            return r
    return None


def _grouped_commits_between(repo_path, from_ref, to_ref):
    """Group the user commits in ``from_ref..to_ref`` of the repo at repo_path.

    Drops vmn's own stamp commits (authored as ``VMN_USER_NAME``). Returns the
    ``group_commits`` dict, or ``None`` when the repo or either ref cannot be
    read locally (e.g. a dependency that is not checked out, or a shallow clone
    missing the range).
    """
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return None
    try:
        commits = [
            (c.message.strip(), c.hexsha[:7])
            for c in repo.iter_commits(f"{from_ref}..{to_ref}")
            if c.author.name != VMN_USER_NAME
        ]
    except git.GitError:
        return None
    finally:
        repo.close()
    return group_commits(commits)


def _dep_changelogs(root_path, from_row, to_row):
    """Per-dependency changelogs for deps whose pin moved between two versions.

    For each changeset entry other than the app itself (``.``), walk the dep
    repo between the two recorded commits. Deps that did not move, are not on
    disk, or cannot be read are omitted.
    """
    from_changesets = from_row.get("changesets", {}) or {}
    to_changesets = to_row.get("changesets", {}) or {}

    deps = []
    for path, to_entry in to_changesets.items():
        if path == ".":
            continue
        to_commit = (to_entry or {}).get("hash")
        from_commit = (from_changesets.get(path) or {}).get("hash")
        if not to_commit or not from_commit or from_commit == to_commit:
            continue

        grouped = _grouped_commits_between(
            os.path.join(root_path, path), from_commit, to_commit
        )
        if grouped is None:
            continue

        deps.append({
            "path": path,
            "name": os.path.basename(path.rstrip("/")),
            "from_commit": from_commit[:7],
            "to_commit": to_commit[:7],
            "breaking": grouped["breaking"],
            "groups": grouped["groups"],
        })

    deps.sort(key=lambda d: d["name"])
    return deps


def version_changelog(root_path, app_name, to_verstr=None, from_verstr=None):
    """Grouped conventional commits between two versions of an app.

    Defaults ``to_verstr`` to the newest version and ``from_verstr`` to that
    version's ``previous_version``. The baseline version (no distinct previous)
    yields an empty changelog rather than an error. Returns ``(result, error)``.
    """
    rows = [r for r in list_versions(root_path, app_name) if r["kind"] == "version"]
    if not rows:
        return None, f"No stamped versions for {app_name}"

    to_row = _row_for(rows, to_verstr) if to_verstr else rows[-1]
    if to_row is None:
        return None, f"Version {to_verstr} not found"

    if from_verstr is None:
        from_verstr = to_row.get("previous_version")
        if from_verstr == to_row["verstr"]:
            from_verstr = None  # baseline previous_version points at itself

    from_row = _row_for(rows, from_verstr) if from_verstr else None

    result = {
        "to_verstr": to_row["verstr"],
        "from_verstr": from_row["verstr"] if from_row else None,
        "to_commit": to_row.get("commit"),
        "from_commit": from_row.get("commit") if from_row else None,
        "breaking": [],
        "groups": [],
        "deps": [],
    }

    if from_row is None:
        return result, None

    # Walk the commits between the two version tags, dropping vmn's own stamp
    # commits — this holds even for a non-adjacent range that spans intermediate
    # versions, since the range runs tag-to-tag.
    grouped = _grouped_commits_between(root_path, from_row["tag"], to_row["tag"])
    if grouped is not None:
        result.update(grouped)

    result["deps"] = _dep_changelogs(root_path, from_row, to_row)
    return result, None
