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


def _tag_yaml(tag_ref):
    """Parse an annotated tag's YAML message; None for lightweight/foreign tags."""
    tag_obj = tag_ref.tag
    if tag_obj is None:
        return None
    try:
        data = yaml.safe_load(tag_obj.message)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def list_versions(root_path, app_name):
    """All stamped versions of an app, oldest first.

    Returns rows with the tag name, verstr, and the stamp metadata the tree
    view needs (previous_version links, release mode, branch, commit,
    changesets, timestamp).
    """
    repo = git.Repo(root_path, search_parent_directories=True)
    try:
        prefix = app_name_to_tag_name(app_name)
        names = repo.git.tag(
            "--sort", "taggerdate", "--list", f"{prefix}_*"
        ).split("\n")

        rows = []
        for name in filter(None, names):
            try:
                props = deserialize_tag_name(name)
            except Exception:
                continue
            if props.app_name != app_name:
                continue

            tag_ref = repo.tags[name]
            data = _tag_yaml(tag_ref) or {}
            stamping = data.get("stamping", {}) or {}

            if "root" in props.types:
                root_app = stamping.get("root_app", {}) or {}
                rows.append({
                    "tag": name,
                    "verstr": str(props.root_version),
                    "root_version": props.root_version,
                    "kind": "root",
                    "services": root_app.get("services", {}),
                    "latest_service": root_app.get("latest_service"),
                    "external_services": root_app.get("external_services", {}),
                    "timestamp": tag_ref.tag.tagged_date if tag_ref.tag else None,
                })
                continue

            app = stamping.get("app", {}) or {}
            changesets = app.get("changesets", {}) or {}
            rows.append({
                "tag": name,
                "verstr": props.verstr,
                "kind": "version",
                "release_mode": app.get("release_mode"),
                "prerelease": app.get("prerelease"),
                "previous_version": app.get("previous_version"),
                "branch": app.get("stamped_on_branch"),
                "commit": (changesets.get(".") or {}).get("hash"),
                "changesets": changesets,
                "timestamp": tag_ref.tag.tagged_date if tag_ref.tag else None,
            })
        return rows
    finally:
        repo.close()
