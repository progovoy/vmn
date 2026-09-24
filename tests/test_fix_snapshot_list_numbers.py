"""`vmn snapshot list` numbers rows by storage index — what `@N` resolves —
whatever `--last` / `--filter` hide."""
import os
import re

import yaml
from helpers import _bootstrap, _snapshot, _storage

from version_stamp.cli.snapshot import _resolve_verstr

_ROW_RE = re.compile(r"^\[(\d+)\]\s+(\S+)")
RUNS = [("0.0.1-dev.aaaa111", "a"), ("0.0.1-dev.bbbb222", "b"), ("0.0.1-dev.cccc333", "a")]


def _seed(app_layout):
    for second, (verstr, kind) in enumerate(RUNS, 1):
        path = os.path.join(
            app_layout.repo_path, ".vmn", app_layout.app_name, "snapshots", verstr
        )
        os.makedirs(path)
        meta = {"verstr": verstr, "timestamp": f"2026-09-21T12:00:{second:02d}Z",
                "user_meta": {"kind": kind}}
        with open(os.path.join(path, "metadata.yml"), "w") as f:
            yaml.dump(meta, f)


def _listed(capfd, app_layout, **kwargs):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", **kwargs) == 0
    lines = capfd.readouterr().out.splitlines()
    return [(int(m.group(1)), m.group(2)) for m in map(_ROW_RE.match, lines) if m]


def _assert_at_n_resolves(app_layout, rows):
    storage = _storage(app_layout, subdir="snapshots")
    for idx, verstr in rows:
        assert _resolve_verstr(storage, app_layout.app_name, f"@{idx}") == (verstr, None)


def test_last_keeps_storage_numbers(app_layout, capfd):
    _bootstrap(app_layout)
    _seed(app_layout)
    rows = _listed(capfd, app_layout, last=2)
    assert rows == [(2, RUNS[1][0]), (3, RUNS[2][0])]
    _assert_at_n_resolves(app_layout, rows)


def test_filter_keeps_storage_numbers(app_layout, capfd):
    _bootstrap(app_layout)
    _seed(app_layout)
    rows = _listed(capfd, app_layout, filter_args=["kind=a"])
    assert rows == [(1, RUNS[0][0]), (3, RUNS[2][0])]
    _assert_at_n_resolves(app_layout, rows)
