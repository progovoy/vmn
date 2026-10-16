"""One ref dispatcher (``resolve_ref.resolve_with``) answers for every
backend through its lookups; the placement interface is shared by the
snapshot and the point view."""
import pytest
from vmn_exp.core.index_point import PointView
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.resolve_ref import (
    AMBIGUOUS_REF,
    INVALID_REF,
    RUN_NOT_FOUND,
    RefLookups,
    resolve_with,
)

RUNS = ["0.0.1-dev.aaa1", "0.0.1-dev.aaa2", "0.0.1-dev.bbb1"]


def _lookups(runs):
    return RefLookups(
        latest=lambda: runs[-1] if runs else None,
        at=lambda n: runs[n - 1] if n <= len(runs) else None,
        count=lambda: len(runs),
        exists=lambda v: v in runs,
        with_prefix=lambda p: sorted(v for v in runs if v.startswith(p)),
    )


@pytest.mark.parametrize("ref, latest, expected", [
    ("latest", False, ("0.0.1-dev.bbb1", None)),
    (None, True, ("0.0.1-dev.bbb1", None)),
    (None, False, (None, None)),
    ("@2", False, ("0.0.1-dev.aaa2", None)),
    ("0.0.1-dev.b", False, ("0.0.1-dev.bbb1", None)),
    ("0.0.1-dev.aaa1", False, ("0.0.1-dev.aaa1", None)),
    ("1.2.3", False, ("1.2.3", None)),
])
def test_resolve_with_answers(ref, latest, expected):
    assert resolve_with(_lookups(RUNS), "app", ref, latest, "experiment") == expected


@pytest.mark.parametrize("runs, ref, message, code", [
    ([], "latest", "No experiments found for app", RUN_NOT_FOUND),
    (RUNS, "@x", "Invalid index reference '@x' (use @N, e.g. @1)", INVALID_REF),
    (RUNS, "@0", "Index '@0' out of range (1..3)", RUN_NOT_FOUND),
    (RUNS, "@4", "Index '@4' out of range (1..3)", RUN_NOT_FOUND),
    (RUNS, "0.0.1-dev.aaa", "Ambiguous prefix '0.0.1-dev.aaa': matches 2 experiments: "
     "0.0.1-dev.aaa1, 0.0.1-dev.aaa2", AMBIGUOUS_REF),
    (RUNS, "0.0.1-dev.z", "Experiment '0.0.1-dev.z' not found", RUN_NOT_FOUND),
])
def test_resolve_with_errors(runs, ref, message, code):
    verstr, err = resolve_with(_lookups(runs), "app", ref, False, "experiment")
    assert verstr is None and err == message and err.code == code


def test_a_snapshot_answers_the_placement_lookups():
    rows = [{"idx": 1, "verstr": "a"}, {"idx": 2, "verstr": "b", "parent": "a"}]
    snap = IndexSnapshot.build("app", 1, rows, {})
    assert snap.parent_of.get("b") == "a" and snap.parent_of.get("a") is None
    assert snap.children_of.get("a") == ["b"] and snap.children_of.get("b") is None


class _GoneStore:
    def resolve_one(self, *args):
        return None  # the database went away


def test_a_point_view_whose_index_went_away_resolves_through_its_fallback():
    snap = IndexSnapshot.build("app", 1, [{"idx": 1, "verstr": "0.0.1-dev.a"}], {})
    view = PointView(_GoneStore(), "app", fallback=lambda: snap)
    assert view.resolve("@1") == ("0.0.1-dev.a", None)
