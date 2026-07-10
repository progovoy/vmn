#!/usr/bin/env python3
"""Read-side changelog: conventional commits between two stamped versions.

A cheap local git read (``git log range``) plus pure grouping — no lock, no
network. Reuses the same conventional-commit grouping the stamper uses.
"""
import git

from version_stamp.core.changelog import group_commits
from version_stamp.core.constants import VMN_USER_NAME
from version_stamp.ui.readers.versions import list_versions


def _row_for(rows, verstr):
    for r in rows:
        if r["verstr"] == verstr:
            return r
    return None


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
    }

    if from_row is None:
        return result, None

    # Walk the commits between the two version tags, dropping vmn's own stamp
    # commits (authored as VMN_USER_NAME) so only user changes remain — this
    # holds even for a non-adjacent range that spans intermediate versions.
    repo = git.Repo(root_path, search_parent_directories=True)
    try:
        commits = [
            (c.message.strip(), c.hexsha[:7])
            for c in repo.iter_commits(f"{from_row['tag']}..{to_row['tag']}")
            if c.author.name != VMN_USER_NAME
        ]
    finally:
        repo.close()

    result.update(group_commits(commits))
    return result, None
