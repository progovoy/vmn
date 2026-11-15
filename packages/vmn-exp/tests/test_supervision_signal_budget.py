"""After a signal, `vmn-exp run`'s wait for its child and its final uploads
together fit 25 s, a pod's default grace period; without one the uploads keep
their long budget (plan 40 C15, owner answer of 2026-11-11)."""
import argparse
import signal
import time

from vmn_exp.cli.run import _kill_graces
from vmn_exp.cli.supervisor import SignalForwarder
from vmn_exp.cli.supervisor_state import final_upload_deadline


def _args(kill_grace_sec=None):
    return argparse.Namespace(kill_grace_sec=kill_grace_sec)


def test_after_a_signal_the_child_wait_and_the_final_upload_fit_25_seconds():
    stop_grace, grace = _kill_graces(_args(), env={})

    deadline = final_upload_deadline(now=110.0, timeout=60, signalled_at=100.0,
                                     signal_grace=grace)

    assert (stop_grace, grace) == (30, 15)
    assert deadline == 125.0


def test_without_a_signal_the_final_upload_keeps_its_long_budget():
    deadline = final_upload_deadline(now=110.0, timeout=60, signalled_at=None,
                                     signal_grace=15)

    assert deadline == 170.0


def test_an_explicit_kill_grace_is_honoured_after_a_signal():
    assert _kill_graces(_args(40), env={}) == (40, 40)
    assert _kill_graces(_args(), env={"VMN_EXP_KILL_GRACE_SEC": "50"}) == (50, 50)
    assert final_upload_deadline(now=0.0, timeout=60, signalled_at=0.0,
                                 signal_grace=40) == 50.0


def test_a_received_signal_starts_the_signal_grace_not_the_stop_grace():
    forwarder = SignalForwarder(30, signal_grace_sec=15, clock=time.monotonic)

    forwarder._handle(signal.SIGTERM, None)

    assert forwarder._kill_at - forwarder.signalled_at == 15


def test_a_stop_request_keeps_the_kill_grace():
    forwarder = SignalForwarder(30, signal_grace_sec=15, clock=time.monotonic)

    forwarder.request_stop()

    assert forwarder.signalled_at is None
    assert forwarder._kill_at is not None
