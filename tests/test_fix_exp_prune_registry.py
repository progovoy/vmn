"""Prune registry guard (C6): registered runs are never deleted, not even with --force.

Seven tests:
1. registered run survives bulk prune (--keep 0)
2. registered run survives --force
3. registered run survives targeted -v prune even with --force
4. registered run survives --query --yes prune
5. deleted model version no longer protects
6. registry read failure deletes nothing and exits non-zero
7. ancestor of a registered run is kept
"""
import pytest
import vmn_exp.registry.view as _reg_view
from helpers import _bootstrap, _exp, _storage

from vmn_exp.registry.log import set_version_status
from vmn_exp.registry.store import ensure_model, register_version


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _verstrs(app_layout):
    return [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]


def _prune(app_layout, capfd, *extra, keep=None):
    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", keep=keep, extra_args=list(extra))
    return err, capfd.readouterr().out


def _register(app_layout, verstr, model="mymodel"):
    """Register *verstr* of *app_layout.app_name* as a version of *model*."""
    st = _storage(app_layout)
    ensure_model(st, model)
    return register_version(
        st, model, {"app": app_layout.app_name, "verstr": verstr}
    )


# ---------------------------------------------------------------------------
# 1. Registered run survives bulk prune
# ---------------------------------------------------------------------------


def test_registered_run_survives_bulk_prune(app_layout, capfd):
    """A run referenced by a non-deleted model version must not be deleted."""
    _bootstrap(app_layout)
    run1 = _create(app_layout)
    run2 = _create(app_layout)
    _register(app_layout, run1)

    err, out = _prune(app_layout, capfd, keep=0)
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert run1 in remaining, "registered run must survive"
    assert run2 not in remaining, "unregistered run must be deleted"
    assert "vmn-exp model delete" in out


# ---------------------------------------------------------------------------
# 2. Registered run survives --force
# ---------------------------------------------------------------------------


def test_registered_run_survives_force(app_layout, capfd):
    """--force overrides live/tag guards but NOT registry protection."""
    _bootstrap(app_layout)
    run = _create(app_layout)
    _create(app_layout)  # second run to ensure there are candidates
    _register(app_layout, run)

    err, out = _prune(app_layout, capfd, "--force", keep=0)
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert run in remaining
    assert "vmn-exp model delete" in out


# ---------------------------------------------------------------------------
# 3. Targeted -v with --force still refuses
# ---------------------------------------------------------------------------


def test_registered_run_survives_targeted_prune_with_force(app_layout, capfd):
    """-v <verstr> --force does not delete a registered run."""
    _bootstrap(app_layout)
    run = _create(app_layout)
    _register(app_layout, run)

    capfd.readouterr()
    err = _exp(app_layout.app_name, action="prune", version=run, extra_args=["--force"])
    out = capfd.readouterr().out
    assert err == 0, out
    assert run in _verstrs(app_layout)
    assert "vmn-exp model delete" in out


# ---------------------------------------------------------------------------
# 4. Query --yes still refuses registered runs
# ---------------------------------------------------------------------------


def test_registered_run_survives_query_prune_with_yes(app_layout, capfd):
    """--query --yes deletes unregistered matches but keeps the registered one."""
    _bootstrap(app_layout)
    run1 = _create(app_layout)
    run2 = _create(app_layout)
    _register(app_layout, run1)

    capfd.readouterr()
    err = _exp(
        app_layout.app_name,
        action="prune",
        extra_args=["--query", 'status = "created"', "--yes"],
    )
    out = capfd.readouterr().out
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert run1 in remaining, "registered run must survive"
    assert run2 not in remaining, "unregistered run must be deleted"
    assert "vmn-exp model delete" in out


# ---------------------------------------------------------------------------
# 5. Deleted model version no longer protects
# ---------------------------------------------------------------------------


def test_deleted_model_version_no_longer_protects(app_layout, capfd):
    """Once the model version is deleted, the run can be pruned."""
    _bootstrap(app_layout)
    run = _create(app_layout)
    st = _storage(app_layout)
    ensure_model(st, "mymodel")
    n = register_version(st, "mymodel", {"app": app_layout.app_name, "verstr": run})
    set_version_status(st, "mymodel", n, "deleted")

    err, out = _prune(app_layout, capfd, keep=0)
    assert err == 0, out
    assert _verstrs(app_layout) == [], "run should be deleted once model version is deleted"


# ---------------------------------------------------------------------------
# 6. Registry read failure deletes nothing and exits non-zero
# ---------------------------------------------------------------------------


def test_registry_read_failure_deletes_nothing_and_exits_nonzero(
    app_layout, capfd, monkeypatch
):
    """A registry read error causes prune to fail closed: nothing deleted, rc != 0."""
    _bootstrap(app_layout)
    run1 = _create(app_layout)
    run2 = _create(app_layout)

    def _boom(storage):
        raise OSError("simulated registry failure")

    monkeypatch.setattr(_reg_view, "registered_runs", _boom)

    err, out = _prune(app_layout, capfd, keep=0)
    assert err != 0, "prune must exit non-zero on registry read failure"
    remaining = _verstrs(app_layout)
    assert run1 in remaining, "no run must be deleted on registry failure"
    assert run2 in remaining, "no run must be deleted on registry failure"


# ---------------------------------------------------------------------------
# 7. Ancestor of a registered run is kept
# ---------------------------------------------------------------------------


def test_ancestor_of_registered_run_is_kept(app_layout, capfd):
    """Ancestors of registry-protected runs are kept (like ancestors of kept descendants)."""
    _bootstrap(app_layout)
    outer = _create(app_layout)
    inner = _create(app_layout, "--parent", outer)
    _register(app_layout, inner)

    err, out = _prune(app_layout, capfd, keep=0)
    assert err == 0, out
    remaining = _verstrs(app_layout)
    assert inner in remaining, "registered inner run must survive"
    assert outer in remaining, "ancestor of registered run must survive"
