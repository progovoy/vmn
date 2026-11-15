"""Bound an in-process job's call by the job timeout (plan 40 C16).

A store action waits on the store; a hung store must not hold its job (and
the workspace's action slot) as ``running`` forever. The call runs on a
thread of its own and the job waits for it at most the job timeout. A call
past it is not cancelled (nothing can cancel a blocked socket read): it keeps
running, and ``returned`` tells when it is finally done.
"""
import threading
from dataclasses import dataclass, field


@dataclass
class Outcome:
    value: object = None
    error: Exception = None
    timed_out: bool = False
    returned: threading.Event = field(default_factory=threading.Event)


class CallTimedOut(Exception):
    """A bounded call did not return in time; ``returned`` is set once it does."""

    def __init__(self, returned):
        super().__init__("the store did not answer")
        self.returned = returned


def run_bounded(call, timeout_sec, start_thread):
    """Run *call* through *start_thread(target)* and wait for it at most
    *timeout_sec*: its :class:`Outcome`, or a timed-out one."""
    done = Outcome()

    def target():
        try:
            done.value = call()
        except Exception as e:
            done.error = e
        finally:
            done.returned.set()

    start_thread(target)
    if done.returned.wait(timeout_sec):
        return done
    return Outcome(timed_out=True, returned=done.returned)


def call_bounded(call, timeout_sec, start_thread):
    """*call()*'s value within *timeout_sec*; raises its error, or
    :class:`CallTimedOut`."""
    outcome = run_bounded(call, timeout_sec, start_thread)
    if outcome.timed_out:
        raise CallTimedOut(outcome.returned)
    if outcome.error is not None:
        raise outcome.error
    return outcome.value
