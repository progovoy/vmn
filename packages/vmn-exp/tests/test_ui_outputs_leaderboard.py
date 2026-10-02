"""The memoized leaderboard over an ``outputs.*`` query, moved across index
generations: rows whose outputs changed leave and join the order right,
though the lean rows never carry their outputs."""
import json
import os

import yaml
from exp_helpers import _storage

import vmn_exp.ui.leaderboard_cache as lc
from vmn_exp.core.index import indexed_snapshot
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

QUERY = 'outputs."media/x/0.png".size > 0'
RUNS = 50  # two changed rows (4 moves) stay under the delta limit: orders move on


def _dir(app_layout, verstr):
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app_layout.app_name, verstr)
    os.makedirs(path, exist_ok=True)
    return path


def _append(app_layout, verstr, entry):
    with open(os.path.join(_dir(app_layout, verstr), "log.w0.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _seed(app_layout):
    for i in range(RUNS):
        verstr = f"0.0.{i + 1}"
        meta = {"verstr": verstr, "code_verstr": verstr,
                "timestamp": f"2026-09-21T12:{i // 60:02d}:{i % 60:02d}"}
        with open(os.path.join(_dir(app_layout, verstr), "metadata.yml"), "w") as f:
            yaml.dump(meta, f)
        _append(app_layout, verstr, {"timestamp": "2026-09-21T13:00:00Z", "type": "metrics",
                                     "values": {"loss": float(i)}})


def _image(ts, size=4):
    return {"timestamp": ts, "type": "image", "name": "x", "step": 0,
            "path": "media/x/0.png", "sha256": "a" * 64, "size": size}


def _page(cache, snap):
    return [r["verstr"] for r in cache.page(snap, {}, sort="loss", query=QUERY)]


def test_an_outputs_query_follows_outputs_across_generations(app_layout, monkeypatch):
    moved_on = []
    advanced = lc._Static.advanced

    def spy(self, *args, **kwargs):
        moved_on.append(advanced(self, *args, **kwargs))
        return moved_on[-1]

    monkeypatch.setattr(lc._Static, "advanced", spy)
    _seed(app_layout)
    storage, app = _storage(app_layout), app_layout.app_name
    _append(app_layout, "0.0.2", _image("2026-09-21T13:01:00Z"))
    cache = LeaderboardCache()
    assert _page(cache, indexed_snapshot(storage, app, wait=True)) == ["0.0.2"]

    _append(app_layout, "0.0.2", _image("2026-09-21T13:02:00Z", size=0))  # re-logged empty
    _append(app_layout, "0.0.5", _image("2026-09-21T13:02:00Z"))
    snap = indexed_snapshot(storage, app, wait=True)
    assert _page(cache, snap) == ["0.0.5"]
    assert moved_on and moved_on[-1] is not None  # moved on, not rebuilt
    assert _page(LeaderboardCache(), snap) == ["0.0.5"]  # what a rebuild answers
