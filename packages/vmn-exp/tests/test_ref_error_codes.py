"""Run-ref resolution errors carry a typed reason (``code``) next to their
unchanged message, so callers (the ui's error bodies) never parse messages."""
import pytest

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.resolve_ref import (
    AMBIGUOUS_REF,
    INVALID_REF,
    RUN_NOT_FOUND,
    _resolve_verstr,
)
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
VERSTRS = ("0.0.1-dev.aaaa1111.1", "0.0.1-dev.aaaa2222.2")


@pytest.fixture
def storage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    for i, v in enumerate(VERSTRS):
        st.save(APP, v, {"verstr": v, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
    return st


@pytest.fixture
def empty(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "empty"), area="runs")


def _snapshot(verstrs=VERSTRS):
    rows = [{"idx": i, "verstr": v, "timestamp": f"t{i}"} for i, v in enumerate(verstrs, 1)]
    return IndexSnapshot.build(APP, 0, rows, {})


CASES = [
    ("@x", INVALID_REF, "Invalid index reference '@x' (use @N, e.g. @1)"),
    ("@9", RUN_NOT_FOUND, "Index '@9' out of range (1..2)"),
    ("0.0.1-dev.zzzz", RUN_NOT_FOUND, "Experiment '0.0.1-dev.zzzz' not found"),
    ("0.0.1-dev.aaaa", AMBIGUOUS_REF,
     "Ambiguous prefix '0.0.1-dev.aaaa': matches 2 experiments: " + ", ".join(VERSTRS)),
]


@pytest.mark.parametrize("ref,code,message", CASES)
def test_storage_resolver_codes(storage, ref, code, message):
    verstr, err = _resolve_verstr(storage, APP, ref, kind="experiment")
    assert verstr is None
    assert err == message
    assert err.code == code


@pytest.mark.parametrize("ref,code,message", CASES)
def test_index_snapshot_resolver_codes(ref, code, message):
    verstr, err = _snapshot().resolve(ref)
    assert verstr is None
    assert err == message
    assert err.code == code


def test_latest_without_runs_is_run_not_found(empty):
    _, err = _resolve_verstr(empty, APP, "latest", kind="experiment")
    assert err.code == RUN_NOT_FOUND
    _, err = _snapshot(()).resolve("latest")
    assert err == f"No experiments found for {APP}"
    assert err.code == RUN_NOT_FOUND


def test_success_has_no_error(storage):
    assert _resolve_verstr(storage, APP, "@1", kind="experiment") == (VERSTRS[0], None)
    assert _snapshot().resolve("@2") == (VERSTRS[1], None)
