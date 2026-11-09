"""Compare and outer-run charts read series through ``/series``; its answer
marks a metric whose steps went back (``step_restarts[verstr][metric] =
{"from", "to"}``) as the run page does, from what it read already: a
``.vmx`` key's footer, any other key's points."""
import os
import tempfile

import pytest

pytest.importorskip("fastapi")

from test_fix_ui_perf_series import APP, BASE, _client

from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_index_reader import MetricIndexReader

V = "1.0.0-dev.a"
T0 = 1_700_000_000_000_001
STEPS = list(range(121)) + list(range(6))
RESTARTED = {"best": {"from": 120, "to": 5}}


def _ts(i):
    return f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}.000001Z"


def _logged(storage, steps=STEPS):
    storage.save(APP, V, {"verstr": V, "timestamp": _ts(0)}, {})
    for i, step in enumerate(steps):
        storage.append_log_entry(APP, V, "w", {"timestamp": _ts(i), "type": "metrics",
                                                "step": step, "values": {"best": 0.5}})


def _compacted(storage):
    storage.save(APP, V, {"verstr": V, "timestamp": _ts(0)}, {})
    cols = Columns(STEPS, [T0 + i for i in range(len(STEPS))], [0.5] * len(STEPS))
    fd, path = tempfile.mkstemp(suffix=".vmx")
    with os.fdopen(fd, "wb") as f:
        f.write(build_index("w", {"best": cols}))
    try:
        assert storage.put_indexed(APP, V, "w", path)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _series(client, **body):
    r = client.post(f"{BASE}/series", json={"verstrs": [V], **body})
    assert r.status_code == 200
    return r.json()


def test_logged_points_that_went_back_are_marked(tmp_path):
    client, storage = _client(tmp_path)
    _logged(storage)
    assert _series(client)["step_restarts"] == {V: RESTARTED}


def test_a_vmx_key_is_marked_from_its_footer(tmp_path, monkeypatch):
    client, storage = _client(tmp_path)
    _compacted(storage)
    raw = []
    original = MetricIndexReader.points
    monkeypatch.setattr(MetricIndexReader, "points",
                        lambda self, *a, **k: raw.append(a) or original(self, *a, **k))
    payload = _series(client, max_points=20)
    assert payload["step_restarts"] == {V: RESTARTED}
    assert not raw  # an LOD slice, no full read


def test_a_zoom_is_marked_too(tmp_path):
    client, storage = _client(tmp_path)
    _compacted(storage)
    assert _series(client, step_min=0, step_max=50)["step_restarts"] == {V: RESTARTED}


def test_monotone_steps_are_not_marked(tmp_path):
    client, storage = _client(tmp_path)
    _logged(storage, list(range(10)))
    assert "step_restarts" not in _series(client)
