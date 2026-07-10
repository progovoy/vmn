#!/usr/bin/env python3
"""Stamp-tree readers: version DAG, root-app topology, dependency graph.

Shapes the raw tag rows from ``readers.versions`` into the structures the UI
draws. All reads are cheap local git operations.
"""
from version_stamp.core.version_math import deserialize_vmn_version
from version_stamp.ui.readers.versions import list_versions


def _base_version(verstr):
    """The release version a (pre)release verstr belongs to (rc chain anchor)."""
    try:
        props = deserialize_vmn_version(verstr)
    except Exception:
        return verstr
    base = f"{props.major}.{props.minor}.{props.patch}"
    if props.hotfix:
        base += f".{props.hotfix}"
    return base


def version_dag(root_path, app_name):
    """Nodes for every stamped version and edges from previous_version links."""
    rows = [r for r in list_versions(root_path, app_name) if r["kind"] == "version"]

    nodes = []
    for r in rows:
        nodes.append({
            "verstr": r["verstr"],
            "base": _base_version(r["verstr"]),
            "release_mode": r.get("release_mode"),
            "prerelease": (
                r.get("prerelease")
                if r.get("prerelease") not in (None, "release") else None
            ),
            "branch": r.get("branch"),
            "commit": r.get("commit"),
            "timestamp": r.get("timestamp"),
        })

    known = {n["verstr"] for n in nodes}
    edges = [
        {"from": r["previous_version"], "to": r["verstr"]}
        for r in rows
        if r.get("previous_version") in known and r["previous_version"] != r["verstr"]
    ]
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
