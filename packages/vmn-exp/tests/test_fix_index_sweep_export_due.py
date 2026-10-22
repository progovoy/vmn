"""A sweep whose full listing is due (never done, requested, or a clock gone
backwards on restore) still exports its state, and a later process restoring
that state finds the full listing still due."""
from vmn_exp.core.index_sweep import Sweep

APP = "app"


def _due_sweep():
    sweep = Sweep(None, APP, full_sweep_sec=300)
    sweep.request_full()
    return sweep


def test_a_sweep_with_a_full_listing_due_exports_its_state():
    state = _due_sweep().export_state(now=100.0, wall=1_000_000.0)

    assert state["last_full"] is None


def test_a_restored_due_state_keeps_the_full_listing_due():
    state = _due_sweep().export_state(now=100.0, wall=1_000_000.0)
    later = Sweep(None, APP, full_sweep_sec=300)

    later.restore_state(state, {}, now=5.0, wall=1_000_010.0)

    assert later._full_due(5.0)
