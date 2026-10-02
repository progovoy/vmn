"""Report header log: title / archived / pinned / published changes.

Entries use the registry's shape ``{type, ts, writer, pos, actor, ...}``
(:mod:`vmn_exp.registry.log`) on the report's ``header`` record and fold
last-writer-wins on ``(ts, writer, pos)``.
"""
from __future__ import annotations

from vmn_exp.core.writer import flush_log
from vmn_exp.registry.fold import _sort_key
from vmn_exp.registry.log import _build_entry
from vmn_exp.storage.areas import REPORTS

HEADER = "header"

# entry type -> (folded field, entry field holding the value)
_FIELDS = {
    "title": ("title", "title"),
    "archived": ("archived", "archived"),
    "pinned": ("pinned", "pinned"),
    "published": ("published_rev", "rev"),
}


def reports_area(storage):
    return storage.in_area(REPORTS)


def read_header_entries(storage, rid):
    return reports_area(storage).load_merged_log(rid, HEADER)


def fold_header(entries):
    """``{title, archived, pinned, published_rev}``; each the latest entry's
    value on ``(ts, writer, pos)``, unset ones left out."""
    latest = {}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") not in _FIELDS:
            continue
        field, source = _FIELDS[entry["type"]]
        key = _sort_key(entry)
        if field not in latest or key >= latest[field][0]:
            latest[field] = (key, entry.get(source))
    return {field: value for field, (_, value) in latest.items()}


def _append(storage, rid, entry_type, actor=None, **fields):
    area = reports_area(storage)
    entry = _build_entry(read_header_entries(storage, rid), entry_type, actor, **fields)
    area.append_log_entry(rid, HEADER, entry["writer"], entry)
    flush_log(area, rid, HEADER)


def set_title(storage, rid, title, *, actor=None):
    _append(storage, rid, "title", actor, title=title)


def set_archived(storage, rid, archived, *, actor=None):
    _append(storage, rid, "archived", actor, archived=bool(archived))


def set_pinned(storage, rid, pinned, *, actor=None):
    _append(storage, rid, "pinned", actor, pinned=bool(pinned))


def set_published(storage, rid, rev, *, actor=None):
    _append(storage, rid, "published", actor, rev=rev)
