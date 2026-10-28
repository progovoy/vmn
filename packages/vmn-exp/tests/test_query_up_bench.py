"""Plan 28 N1's cost bound: an ``up`` field over a fleet-shaped tree (launch →
date → study → trial → pod) costs one ancestor read per ancestor and field,
then about what a plain field costs per run."""
import time

import pytest
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.query import filter_rows
from vmn_exp.core.query_extra import lean_extra

DATES, STUDIES, TRIALS, PODS = 20, 25, 20, 9  # 20 x 25 x 20 x 10 ≈ 100k runs
UP_QUERY = 'up(tags.kind = "study").params.group = "g3" and up.params.trade_date = "d7"'
PLAIN_QUERY = 'params.group = "g3" and params.trade_date = "d7"'


def _row(verstr, parent, kind, **params):
    return {"verstr": verstr, "parent": parent, "params": params, "tags": {"kind": kind},
            "metrics": {}, "name": None}


def _fleet():
    rows = [_row("L", None, "launch")]
    for d in range(DATES):
        date = f"D{d}"
        rows.append(_row(date, "L", "date", trade_date=f"d{d}"))
        for s in range(STUDIES):
            study = f"{date}.S{s}"
            rows.append(_row(study, date, "study", group=f"g{s % 5}"))
            for t in range(TRIALS):
                trial = f"{study}.T{t}"
                rows.append(_row(trial, study, "trial", lr=t))
                rows.extend(_row(f"{trial}.P{p}", trial, "pod") for p in range(PODS))
    return IndexSnapshot.build("app", 1, rows, {})


def _timed(snap, text):
    start = time.perf_counter()
    kept = filter_rows(snap.rows, text, extra=lean_extra(snap))
    return time.perf_counter() - start, kept


@pytest.mark.serial
def test_an_up_query_costs_about_a_plain_one():
    snap = _fleet()
    assert len(snap.rows) > 100_000
    cold, kept = _timed(snap, UP_QUERY)
    assert len(kept) == STUDIES // 5 * TRIALS * (PODS + 1)
    warm, _ = _timed(snap, UP_QUERY)
    plain = min(_timed(snap, PLAIN_QUERY)[0] for _ in range(3))
    print(f"\nup cold {cold:.3f}s, warm {warm:.3f}s, plain {plain:.3f}s")
    assert cold < 3.0
    assert warm < 4 * plain + 0.2
