#!/usr/bin/env python3
"""The digest and URI maps lineage joins rows over, and the ``vmn://``
artifact URIs and digests they are keyed by (see :mod:`vmn_exp.core.lineage`).

Pure: no storage, no clock.
"""
from operator import itemgetter

from vmn_exp.registry.names import parse_registry_uri

SCHEME = "vmn://"
_KINDS = ("producers", "digest_consumers", "uri_consumers")


def artifact_ref_uri(app_name, verstr, path):
    """``vmn://<app tag>/<verstr>/<path>`` naming artifact *path* of a run."""
    return f"{SCHEME}{app_name.replace('/', '-')}/{verstr}/{path}"


def parse_artifact_uri(uri):
    """``(app_name, verstr, path)`` of a ``vmn://`` artifact URI, else None."""
    if not isinstance(uri, str) or not uri.startswith(SCHEME):
        return None
    parts = uri[len(SCHEME):].split("/", 2)
    if len(parts) != 3 or not all(parts):
        return None
    app_tag, verstr, path = parts
    return app_tag.replace("-", "/"), verstr, path


def normalize_digest(digest):
    """A digest compared case- and ``sha256:``-prefix-insensitively; None if empty."""
    if not isinstance(digest, str) or not digest.strip():
        return None
    value = digest.strip().lower()
    return value[len("sha256:"):] if value.startswith("sha256:") else value


class LineageIndex:
    """The digest and URI maps of one app's rows. Build once per index
    snapshot, or move the previous snapshot's along (:meth:`moved`).

    *outputs_of(verstr)* gives a row's outputs when its rows are an index
    snapshot's lean ones (``IndexSnapshot.outputs_of``); else they are read
    off the rows. Each group lists its entries in row order.
    """

    def __init__(self, rows, outputs_of=None):
        self.row_list = tuple(rows)
        self.rows = {}
        self.outputs_of = outputs_of or self._row_outputs
        self.producers = {}  # digest -> [(verstr, artifact path)]
        self.digest_consumers = {}  # digest -> [(verstr, input name, input digest)]
        self.uri_consumers = {}  # (app, verstr) -> [(verstr, input name, input digest, path)]
        for row in self.row_list:
            self.rows[row["verstr"]] = row
            for kind, key, entry in self.entries(row):
                getattr(self, kind).setdefault(key, []).append(entry)

    def _row_outputs(self, verstr):
        return self.rows[verstr].get("outputs") or {}

    def entries(self, row):
        """``[(map name, key, entry)]`` *row* adds to the maps."""
        verstr, found = row["verstr"], []
        for path, out in self.outputs_of(verstr).items():
            digest = normalize_digest((out or {}).get("digest"))
            if digest:
                found.append(("producers", digest, (verstr, path)))
        for name, inp in (row.get("inputs") or {}).items():
            inp = inp or {}
            ref = parse_artifact_uri(inp.get("uri"))
            if ref:
                found.append(("uri_consumers", ref[:2], (verstr, name, inp.get("digest"), ref[2])))
                continue
            digest = normalize_digest(inp.get("digest"))
            if digest and not parse_registry_uri(inp.get("uri")):
                found.append(("digest_consumers", digest, (verstr, name, inp.get("digest"))))
        return found

    @classmethod
    def moved(cls, prev, rows, outputs_of, joined, left):
        """*prev* (left unchanged) moved to *rows*, each row carrying its
        ``idx``: *joined* = the rows of *rows* that are not *prev*'s row
        objects, in row order; *left* = *prev*'s rows that are not in *rows*.
        Verstrs must be unique. Costs the delta plus the groups it touches."""
        index = cls.__new__(cls)
        index.row_list = tuple(rows)
        index.outputs_of = outputs_of or index._row_outputs
        index.rows = dict(prev.rows)
        for kind in _KINDS:
            setattr(index, kind, dict(getattr(prev, kind)))
        joined_rows = {row["verstr"]: row for row in joined}
        for row in left:
            if row["verstr"] not in joined_rows:
                del index.rows[row["verstr"]]
        index.rows.update(joined_rows)
        was, now = _grouped(prev, left), _grouped(index, joined)
        for group in was.keys() | now.keys():
            gone, added = _changes(was.get(group, {}), now.get(group, {}))
            if gone or added:
                index._regroup(group, gone, added)
        return index

    def _regroup(self, group, old, new):
        """Swap *group*'s entries *old* for *new* (each ``{verstr: (idx,
        entries)}``), keeping row order; *group*'s list is replaced, not changed."""
        kind, key = group
        groups = getattr(self, kind)
        entries = groups.get(key, ())
        kept = [entry for entry in entries if entry[0] not in old] if old else list(entries)
        added = [entry for _, of_row in sorted(new.values(), key=itemgetter(0)) for entry in of_row]
        if kept and added and self._idx(added[0]) < self._idx(kept[-1]):
            for entry in added:
                kept.insert(self._after(kept, self._idx(entry)), entry)
        else:
            kept += added
        if kept:
            groups[key] = kept
        else:
            groups.pop(key, None)

    def _idx(self, entry):
        return self.rows[entry[0]]["idx"]

    def _after(self, entries, idx):
        """Where an entry of row *idx* goes in *entries* (in row order): after
        every entry of a row up to *idx* (a bisect; 3.8's has no ``key``)."""
        lo, hi = 0, len(entries)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._idx(entries[mid]) <= idx:
                lo = mid + 1
            else:
                hi = mid
        return lo


def _changes(old, new):
    """The verstrs of *old* and of *new* whose ``(idx, entries)`` differ."""
    return ({v: x for v, x in old.items() if new.get(v) != x},
            {v: x for v, x in new.items() if old.get(v) != x})


def _grouped(index, rows):
    """``{(map name, key): {verstr: (idx, entries)}}`` of *rows*' entries."""
    grouped = {}
    for row in rows:
        for kind, key, entry in index.entries(row):
            per_row = grouped.setdefault((kind, key), {})
            per_row.setdefault(row["verstr"], (row["idx"], []))[1].append(entry)
    return grouped
