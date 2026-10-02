"""Report records in the ``reports`` area (docs/plans/13-reports-comments.md §3.1).

One scope per report ``<rid>``: a ``header`` record (its log carries the
mutable title/archived/pinned/published) and immutable revisions ``v<N>``
claimed with ``create_exclusive``, the body in ``report.md``. The latest
revision is the highest ``v<N>`` that exists.
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass

from vmn_exp.core.record_format import stamped
from vmn_exp.registry.fold import now_iso
from vmn_exp.registry.log import actor_identity
from vmn_exp.reports.log import HEADER, fold_header, read_header_entries, reports_area, set_title

BODY_FILE = "report.md"
_B32 = "abcdefghijklmnopqrstuvwxyz234567"
_SETTLE_SEC = 5
_REVISION_RE = re.compile(r"^v([1-9][0-9]*)$")


@dataclass
class Conflict:
    """A save lost: revision *rev* (by *author*) was saved first."""

    rev: int
    body: str
    author: dict


def new_rid():
    return "r" + "".join(secrets.choice(_B32) for _ in range(12))


def create(storage, title, body, *, actor=None):
    """Claim a new report's header and v1; return its rid."""
    area = reports_area(storage)
    actor = actor or actor_identity()
    rid = new_rid()
    while not area.create_exclusive(rid, HEADER, _header_metadata(actor), {}):
        rid = new_rid()
    set_title(storage, rid, title, actor=actor)
    _claim_revision(area, rid, 1, body, "", actor)
    return rid


def save(storage, rid, base, body, message="", *, actor=None):
    """Save *body* as revision ``base + 1``: its number, or a :class:`Conflict`
    carrying the latest revision when another save took the slot first."""
    area = reports_area(storage)
    if _claim_revision(area, rid, base + 1, body, message, actor or actor_identity()):
        return base + 1
    latest = _settled_latest(storage, rid)
    return Conflict(latest["rev"], latest["body"], latest.get("author") or {})


def latest_rev(storage, rid):
    names = reports_area(storage).list_record_names(rid)
    return max((_revision_number(name) or 0 for name in names), default=0)


def revision(storage, rid, n):
    """Revision *n*'s metadata plus ``rev`` and ``body``, or None."""
    area = reports_area(storage)
    name = f"v{n}"
    metadata = area.load_metadata(rid, name)
    if metadata is None:
        return None
    raw = area.load_file(rid, name, BODY_FILE)
    if raw is None:
        return None  # claimed, body not written yet
    return dict(metadata, rev=n, body=raw.decode("utf-8"))


def get(storage, rid):
    """The report: header fold + its latest revision, or None."""
    header = reports_area(storage).load_metadata(rid, HEADER)
    if header is None:
        return None
    latest = _newest_complete(storage, rid, latest_rev(storage, rid)) or {"rev": 0, "body": ""}
    return {"rid": rid, "created_at": header.get("created_at"),
            "created_by": header.get("created_by"), "archived": False, "pinned": False,
            "published_rev": None, **fold_header(read_header_entries(storage, rid)),
            "rev": latest["rev"], "body": latest["body"], "author": latest.get("author")}


def list_reports(storage):
    """Every readable report, as :func:`get` returns it."""
    reports = (get(storage, rid) for rid in reports_area(storage).list_apps())
    return [report for report in reports if report is not None]


def delete(storage, rid):
    """Delete every record of report *rid* (header last: it marks the report)."""
    area = reports_area(storage)
    for name in sorted(area.list_record_names(rid), key=lambda n: n == HEADER):
        area.delete(rid, name)


def _settled_latest(storage, rid):
    """The latest revision once its writer has finished it (a claim is
    published before its metadata and body); after the wait, the newest
    complete one below an abandoned claim."""
    n = latest_rev(storage, rid)
    deadline = time.monotonic() + _SETTLE_SEC
    while time.monotonic() < deadline:
        found = revision(storage, rid, n)
        if found is not None:
            return found
        time.sleep(0.05)
    return _newest_complete(storage, rid, n - 1)


def _newest_complete(storage, rid, n):
    """The highest complete revision <= *n*, or None."""
    return next(filter(None, (revision(storage, rid, k) for k in range(n, 0, -1))), None)


def _header_metadata(actor):
    return stamped({"verstr": HEADER, "type": "report_header", "created_at": now_iso(),
                    "created_by": actor})


def _claim_revision(area, rid, n, body, message, actor):
    metadata = stamped({"verstr": f"v{n}", "type": "report_revision", "base": n - 1,
                        "author": actor, "created_at": now_iso(), "message": message})
    if not area.create_exclusive(rid, f"v{n}", metadata, {}):
        return False
    area.save_file(rid, f"v{n}", BODY_FILE, body.encode("utf-8"))
    return True


def _revision_number(name):
    match = _REVISION_RE.match(name)
    return int(match.group(1)) if match else None
