#!/usr/bin/env python3
"""Read-side access to stamped versions (git tags) for the vmn ui API.

Everything here is a cheap local git read (``git tag``, annotated-tag YAML) —
no lock, no network, no working-tree access.
"""
import git
import yaml

from version_stamp.core.version_math import (
    app_name_to_tag_name,
    deserialize_tag_name,
)

_FIELD_SEP = "\x00"
_RECORD_SEP = "\x1e"
# One ``git for-each-ref`` pass yields every tag's name, type, date and message,
# instead of resolving each tag (and re-reading packed-refs) one at a time.
_TAG_FORMAT = (
    "%(refname:strip=2)%00%(objecttype)%00%(taggerdate:unix)%00%(contents)%1e"
)


def _message_yaml(message):
    """Parse an annotated tag's YAML message; None for foreign/invalid ones."""
    try:
        data = yaml.safe_load(message)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _app_tags(repo, prefix):
    """``[(name, stamp_yaml_or_None, tagger_epoch_or_None)]`` oldest first.

    Lightweight tags carry no message and no tagger date, so both are None.
    """
    out = repo.git.for_each_ref(
        "--sort=taggerdate", f"--format={_TAG_FORMAT}", f"refs/tags/{prefix}_*"
    )
    tags = []
    for record in out.split(_RECORD_SEP):
        record = record.lstrip("\n")
        if not record:
            continue
        name, obj_type, tagger_date, message = record.split(_FIELD_SEP, 3)
        if obj_type != "tag":
            tags.append((name, None, None))
            continue
        tags.append(
            (name, _message_yaml(message), int(tagger_date) if tagger_date else None)
        )
    return tags


def version_counts(root_path):
    """Stamped-version tag count per app, for dashboard tiles — one
    ``git tag`` pass over the repo, no YAML parse."""
    try:
        repo = git.Repo(root_path, search_parent_directories=True)
    except git.GitError:
        return {}
    try:
        counts = {}
        for name in filter(None, repo.git.tag("--list").split("\n")):
            try:
                app_name = deserialize_tag_name(name).app_name
            except Exception:
                continue
            counts[app_name] = counts.get(app_name, 0) + 1
        return counts
    finally:
        repo.close()


def list_versions(root_path, app_name):
    """All stamped versions of an app, oldest first.

    Returns rows with the tag name, verstr, and the stamp metadata the tree
    view needs (previous_version links, release mode, branch, commit,
    changesets, timestamp).
    """
    repo = git.Repo(root_path, search_parent_directories=True)
    try:
        prefix = app_name_to_tag_name(app_name)

        rows = []
        for name, data, timestamp in _app_tags(repo, prefix):
            try:
                props = deserialize_tag_name(name)
            except Exception:
                continue
            if props.app_name != app_name:
                continue

            stamping = (data or {}).get("stamping", {}) or {}

            if "root" in props.types:
                root_app = stamping.get("root_app", {}) or {}
                rows.append(
                    {
                        "tag": name,
                        "verstr": str(props.root_version),
                        "root_version": props.root_version,
                        "kind": "root",
                        "services": root_app.get("services", {}),
                        "latest_service": root_app.get("latest_service"),
                        "external_services": root_app.get("external_services", {}),
                        "timestamp": timestamp,
                    }
                )
                continue

            app = stamping.get("app", {}) or {}
            changesets = app.get("changesets", {}) or {}
            rows.append(
                {
                    "tag": name,
                    "verstr": props.verstr,
                    "kind": "version",
                    "release_mode": app.get("release_mode"),
                    "prerelease": app.get("prerelease"),
                    "previous_version": app.get("previous_version"),
                    "branch": app.get("stamped_on_branch"),
                    "commit": (changesets.get(".") or {}).get("hash"),
                    "changesets": changesets,
                    "timestamp": timestamp,
                }
            )
        return rows
    finally:
        repo.close()
