"""Find the records of a v1 store and their layout-2 places.

v1 repo-local / ``file://`` / ``--dir``: ``.vmn/<app path>/{experiments,snapshots}/<rec>/``,
pseudo-apps ``.vmn/vmn-code/<app~>/``, ``.vmn/vmn-sweeps/<app~>~<sweep>/`` and
``.vmn/vmn-registry/`` (records in their ``experiments/``).
v1 object stores: ``<prefix>/<app key>/<rec>/`` — the prefixes ``vmn-experiments``
and ``vmn-snapshots``, or one shared URI path (runs carry a log, ``run_state.yml`` or
``format_version``; snapshots none of them, though they have ``code_verstr``); pseudo-apps ``vmn-code-<app~>``, ``vmn-sweeps-<app~>~<sweep>``,
``vmn-registry``.
"""
from dataclasses import dataclass
from typing import List, Optional

import yaml

from vmn_exp.storage import areas
from vmn_exp.storage.store_marker import MARKER

METADATA = "metadata.yml"
_CONTAINERS = {"experiments": areas.RUNS, "snapshots": areas.SNAPSHOTS}
_V2_TOP = {areas.RUNS, areas.SNAPSHOTS, areas.CODE, areas.SWEEPS, areas.REGISTRY,
           areas.REPORTS, areas.COMMENTS, areas.JOURNAL, MARKER}


@dataclass
class Record:
    src: str  # the v1 record's key prefix
    names: List[str]  # its files, record-relative
    area: Optional[str]  # None: a run or a snapshot, told apart by metadata
    scope: str
    name: str


def _sweep_scope(seg):
    app, _, sweep = seg.rpartition("~")
    return f"{app.replace('~', '-')}~{sweep}"


def _registry_place(rec):
    if rec.endswith("-uses"):
        return rec[: -len("-uses")], "uses"
    model, dot, n = rec.rpartition(".v")
    if dot and model and n.isdigit():
        return model, f"v{n}"
    return rec, "header"


def _place(app_seg, rec, area, sep):
    """``(area, scope, name)`` of a record of the v1 app segment *app_seg*."""
    if app_seg == "vmn-registry":
        return (areas.REGISTRY, *_registry_place(rec))
    for pseudo, to_area, scope_of in (
        ("vmn-code", areas.CODE, lambda s: s.replace("~", "-")),
        ("vmn-sweeps", areas.SWEEPS, _sweep_scope),
    ):
        if app_seg.startswith(pseudo + sep):
            return to_area, scope_of(app_seg[len(pseudo) + 1:]), rec
    return area, areas.app_key(app_seg), rec


def _group(keys, prefix, depth):
    """``{record prefix: [names]}``: a record is *depth* segments below *prefix*."""
    groups = {}
    start = len(prefix) + 1 if prefix else 0
    for key in keys:
        segs = key[start:].split("/")
        if len(segs) <= depth or any(s.startswith(".") for s in segs[:depth]):
            continue
        rec = "/".join(segs[:depth])
        groups.setdefault(rec, []).append("/".join(segs[depth:]))
    return groups


def local_records(tree, vmn_dir, skip):
    """``(records, container dirs)`` below the v1 ``.vmn`` dir *vmn_dir*
    (minus the v2 root *skip*)."""
    found, containers = [], set()
    for key in tree.keys(vmn_dir):
        if skip and key.startswith(skip + "/"):
            continue
        segs = key[len(vmn_dir) + 1:].split("/")
        hit = next((i for i, s in enumerate(segs[:-1]) if s in _CONTAINERS and i), None)
        if hit is None:
            continue
        containers.add("/".join([vmn_dir, *segs[: hit + 1]]))
        if hit + 2 >= len(segs) or segs[hit + 1].startswith("."):
            continue
        app, rec = "/".join(segs[:hit]), segs[hit + 1]
        src = "/".join([vmn_dir, *segs[: hit + 2]])
        found.append((app, rec, src, _CONTAINERS[segs[hit]], "/".join(segs[hit + 2:])))
    return _records(found, "/"), containers


def _records(found, sep):
    by_src = {}
    for app, rec, src, area, name in found:
        if src not in by_src:
            by_src[src] = Record(src, [], *_place(app, rec, area, sep))
        by_src[src].names.append(name)
    return list(by_src.values())


def object_records(tree, prefix, area):
    """The records below the v1 *prefix* (*area* None: runs and snapshots share it)."""
    found = []
    for rec_path, names in _group(tree.keys(prefix), prefix, 2).items():
        app_seg, rec = rec_path.split("/")
        if app_seg in _V2_TOP:
            continue
        src = f"{prefix}/{rec_path}" if prefix else rec_path
        found += [(app_seg, rec, src, area, n) for n in names]
    return _records(found, "-")


def classify(record, metadata_text):
    """Settle a shared-prefix record's area from its metadata; legacy ``_``
    app keys take the app name the metadata records."""
    meta = yaml.safe_load(metadata_text) if metadata_text else None
    meta = meta if isinstance(meta, dict) else {}
    if record.area is None:
        is_run = "format_version" in meta or any(
            n.startswith("log") or n == "run_state.yml" for n in record.names)
        record.area = areas.RUNS if is_run else areas.SNAPSHOTS
    if record.area in (areas.RUNS, areas.SNAPSHOTS) and meta.get("app_name"):
        record.scope = areas.app_key(meta["app_name"])
    return record


def v2_prefix(root, record):
    path = f"{record.area}/{record.scope}/{record.name}"
    return f"{root}/{path}" if root else path
