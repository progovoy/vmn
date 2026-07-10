#!/usr/bin/env python3
"""Stamp-tree readers: version DAG, root-app topology, dependency graph.

Shapes the raw tag rows from ``readers.versions`` into the structures the UI
draws. All reads are cheap local git operations.
"""
from version_stamp.core.version_math import get_base_vmn_version
from version_stamp.ui.readers.versions import list_versions


def _base_version(verstr):
    """The release version a (pre)release verstr belongs to (rc chain anchor)."""
    try:
        return get_base_vmn_version(verstr, hide_zero_hotfix=True)
    except Exception:
        return verstr


def _row_rank(row):
    """Canonical-node order within a commit: release, then rc, then metadata."""
    if row.get("prerelease") == "metadata":
        return 2
    if row.get("prerelease") in (None, "release"):
        return 0
    return 1


def version_dag(root_path, app_name):
    """Nodes for every stamped commit and edges from previous_version links.

    Tags sharing a commit (a promoted release, its final rc, build-metadata
    versions) merge into one node — the release — with the rest as aliases.
    """
    rows = [r for r in list_versions(root_path, app_name) if r["kind"] == "version"]

    groups = []
    by_key = {}
    for r in rows:
        key = (r.get("commit"), _base_version(r["verstr"]))
        group = by_key.get(key) if r.get("commit") is not None else None
        if group is not None:
            group.append(r)
        else:
            group = [r]
            by_key[key] = group
            groups.append(group)

    canonical = {}
    nodes = []
    for group in groups:
        group.sort(key=_row_rank)
        head = group[0]
        for r in group:
            canonical[r["verstr"]] = head["verstr"]
        nodes.append({
            "verstr": head["verstr"],
            "base": _base_version(head["verstr"]),
            "release_mode": head.get("release_mode"),
            "prerelease": (
                head.get("prerelease")
                if head.get("prerelease") not in (None, "release") else None
            ),
            "branch": head.get("branch"),
            "commit": head.get("commit"),
            "timestamp": head.get("timestamp"),
            "aliases": [r["verstr"] for r in group[1:]],
        })

    edges = []
    seen = set()
    for r in rows:
        src = canonical.get(r.get("previous_version"))
        dst = canonical[r["verstr"]]
        if src is None or src == dst or (src, dst) in seen:
            continue
        seen.add((src, dst))
        edges.append({"from": src, "to": dst})
    return {"nodes": nodes, "edges": edges}


def root_topology(root_path, root_app_name):
    """Service topology per root version, oldest first, with per-step deltas."""
    rows = [r for r in list_versions(root_path, root_app_name) if r["kind"] == "root"]
    rows.sort(key=lambda r: r["root_version"])

    topology = []
    prev_services = {}
    for r in rows:
        services = r.get("services", {}) or {}
        changed = sorted(
            name for name, ver in services.items()
            if prev_services.get(name) != ver
        )
        removed = sorted(set(prev_services) - set(services))
        topology.append({
            "root_version": r["root_version"],
            "services": services,
            "latest_service": r.get("latest_service"),
            "external_services": r.get("external_services", {}),
            "changed": changed,
            "removed": removed,
            "timestamp": r.get("timestamp"),
        })
        prev_services = services
    return topology


def _changesets_for(rows, verstr):
    for r in rows:
        if r["verstr"] == verstr:
            return r.get("changesets", {}) or {}
    return None


def dep_graph(root_path, app_name, verstr=None, to_verstr=None):
    """Dependency pins of a version; with ``to_verstr``, the drift between two."""
    rows = [r for r in list_versions(root_path, app_name) if r["kind"] == "version"]
    if not rows:
        return None, f"No stamped versions for {app_name}"

    if verstr is None:
        verstr = rows[-1]["verstr"]
    changesets = _changesets_for(rows, verstr)
    if changesets is None:
        return None, f"Version {verstr} not found"

    nodes = [
        {
            "path": path,
            "hash": (info or {}).get("hash"),
            "remote": (info or {}).get("remote"),
            "vcs_type": (info or {}).get("vcs_type"),
        }
        for path, info in sorted(changesets.items())
    ]
    result = {"verstr": verstr, "nodes": nodes}

    if to_verstr:
        to_changesets = _changesets_for(rows, to_verstr)
        if to_changesets is None:
            return None, f"Version {to_verstr} not found"
        drift = [
            {
                "path": path,
                "from": (changesets.get(path) or {}).get("hash"),
                "to": (to_changesets.get(path) or {}).get("hash"),
            }
            for path in sorted(set(changesets) | set(to_changesets))
        ]
        result["to_verstr"] = to_verstr
        result["drift"] = drift

    return result, None
