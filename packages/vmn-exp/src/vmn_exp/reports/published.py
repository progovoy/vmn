"""Published panel data of a report revision: ``v<N>/data/<panel-id>.json``
(docs/plans/13-reports-comments.md §6),
listed by ``data/index.json`` (written after the panels)."""
from __future__ import annotations

import json

from vmn_exp.reports.log import reports_area, set_published

DATA_DIR = "data/"
INDEX_FILE = DATA_DIR + "index.json"


def _data_file(panel_id):
    return f"{DATA_DIR}{panel_id}.json"


def publish(storage, rid, rev, data, *, actor=None):
    """Write each panel's payload of *data* into revision *rev*, then mark it
    published (the header entry last, so readers never see partial data)."""
    area = reports_area(storage)
    for panel_id, payload in data.items():
        area.save_file(rid, f"v{rev}", _data_file(panel_id), _encode(payload))
    area.save_file(rid, f"v{rev}", INDEX_FILE, _encode(sorted(data)))
    set_published(storage, rid, rev, actor=actor)


def panel_ids(storage, rid, rev):
    """The panels revision *rev* has published data for, sorted."""
    raw = reports_area(storage).load_file(rid, f"v{rev}", INDEX_FILE)
    return [] if raw is None else json.loads(raw)


def panel_data(storage, rid, rev, panel_id):
    """Panel *panel_id*'s published payload, or None."""
    if panel_id not in panel_ids(storage, rid, rev):
        return None
    return json.loads(reports_area(storage).load_file(rid, f"v{rev}", _data_file(panel_id)))


def _encode(value):
    return json.dumps(value).encode("utf-8")
