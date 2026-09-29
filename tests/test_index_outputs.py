"""Run outputs through the experiment index.

A run logging an image per step has an ``outputs`` entry per step, so the
index keeps them off the lean rows the leaderboard pages (and facets and
columns) are made of, per verstr beside them like ``metric_summary``. Row
copies handed to the CLI and the reader API carry them again, and queries
over ``outputs.*`` and the lineage index read them from the snapshot.
"""
import json
import os

import pytest
import yaml
from helpers import _exp, _storage

from vmn_exp.core.index import direct_snapshot, indexed_snapshot, indexed_status_rows
from vmn_exp.core.lineage import LineageIndex
from vmn_exp.core.query import filter_rows

SHA = "a" * 64
QUERY = 'outputs."media/x/0.png".size > 0'


def _exp_dir(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    os.makedirs(path, exist_ok=True)
    return path


def _write(app_layout, verstr, second, entries=()):
    meta = {"verstr": verstr, "code_verstr": verstr,
            "timestamp": f"2026-09-21T12:00:{second:02d}"}
    with open(os.path.join(_exp_dir(app_layout, verstr), "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    _append(app_layout, verstr, entries)


def _append(app_layout, verstr, entries):
    with open(os.path.join(_exp_dir(app_layout, verstr), "log.w0.jsonl"), "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _image(step, sha=SHA, size=7):
    return {"timestamp": f"2026-09-21T12:05:{step:02d}Z", "type": "image", "name": "x",
            "step": step, "path": f"media/x/{step}.png", "sha256": sha, "size": size}


def _seed(app_layout):
    _write(app_layout, "0.0.1", 1, [_image(0)])
    _write(app_layout, "0.0.2", 2, [{"timestamp": "2026-09-21T12:05:00Z", "type": "metrics",
                                     "values": {"loss": 1.0}}])


def _outputs(rows):
    return {r["verstr"]: sorted(r["outputs"]) for r in rows}


@pytest.fixture(params=["index", "direct"])
def snapshot_of(request):
    if request.param == "index":
        return lambda app_layout: indexed_snapshot(
            _storage(app_layout), app_layout.app_name, wait=True
        )
    return lambda app_layout: direct_snapshot(_storage(app_layout), app_layout.app_name)


def test_snapshot_rows_are_lean_and_outputs_sit_beside_them(app_layout, snapshot_of):
    _seed(app_layout)
    snap = snapshot_of(app_layout)
    assert all("outputs" not in row for row in snap.rows)
    assert sorted(snap.outputs_of("0.0.1")) == ["media/x/0.png"]
    assert snap.outputs_of("0.0.1")["media/x/0.png"]["digest"] == f"sha256:{SHA}"
    assert snap.outputs_of("0.0.2") == {}


def test_row_copies_carry_outputs(app_layout):
    _seed(app_layout)
    rows, _, _ = indexed_status_rows(_storage(app_layout), app_layout.app_name)
    assert _outputs(rows) == {"0.0.1": ["media/x/0.png"], "0.0.2": []}


def test_a_query_over_outputs_reaches_lean_rows(app_layout, snapshot_of):
    _seed(app_layout)
    snap = snapshot_of(app_layout)
    rows = filter_rows(snap.rows, QUERY, extra={"outputs": snap.outputs_of})
    assert [r["verstr"] for r in rows] == ["0.0.1"]
    assert all("outputs" not in row for row in rows)  # evaluated on, not handed out


def test_lineage_index_of_a_snapshot_reads_its_outputs(app_layout, snapshot_of):
    _seed(app_layout)
    snap = snapshot_of(app_layout)
    index = LineageIndex(snap.rows, outputs_of=snap.outputs_of)
    assert index.producers[SHA] == [("0.0.1", "media/x/0.png")]


def test_incremental_refresh_keeps_outputs_right(app_layout):
    _seed(app_layout)
    storage = _storage(app_layout)
    indexed_snapshot(storage, app_layout.app_name, wait=True)
    _append(app_layout, "0.0.1", [_image(1, sha="b" * 64)])
    _append(app_layout, "0.0.2", [_image(0, size=3)])
    _append(app_layout, "0.0.1", [_image(0, sha="c" * 64, size=9)])  # re-logged step 0
    snap = indexed_snapshot(storage, app_layout.app_name, wait=True)
    assert sorted(snap.outputs_of("0.0.1")) == ["media/x/0.png", "media/x/1.png"]
    assert snap.outputs_of("0.0.1")["media/x/0.png"]["size"] == 9
    assert snap.outputs_of("0.0.2")["media/x/0.png"]["size"] == 3
    rows = filter_rows(snap.rows, 'outputs."media/x/1.png".size > 0',
                       extra={"outputs": snap.outputs_of})
    assert [r["verstr"] for r in rows] == ["0.0.1"]


def test_a_retracted_output_leaves_the_index(app_layout):
    _seed(app_layout)
    storage = _storage(app_layout)
    indexed_snapshot(storage, app_layout.app_name, wait=True)
    _append(app_layout, "0.0.1", [{"timestamp": "2026-09-21T12:06:00Z",
                                   "type": "output_failed", "path": "media/x/0.png"}])
    snap = indexed_snapshot(storage, app_layout.app_name, wait=True)
    assert snap.outputs_of("0.0.1") == {}


def test_cli_list_query_and_json_reach_outputs(app_layout, capfd):
    _seed(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list", extra_args=["--query", QUERY, "--json"]) == 0
    rows = json.loads(capfd.readouterr().out)
    assert [r["verstr"] for r in rows] == ["0.0.1"]
    assert sorted(rows[0]["outputs"]) == ["media/x/0.png"]
