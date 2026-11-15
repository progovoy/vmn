"""The supervision loop of ``vmn-exp run``, with its clock and child wait injected."""
import subprocess


def watch(child_exited, wait_child, tick, clock, interval):
    """Run ``tick(clock())`` once per *interval* while the child lives.

    ``wait_child(timeout)`` blocks until the child exits or *timeout* passes
    and reports whether it exited, so the loop returns at the exit itself.
    """
    if child_exited():
        return
    while True:
        tick(clock())
        if wait_child(interval):
            return


def popen_waiter(proc):
    """``watch``'s wait_child for a ``Popen``: True once *proc* has exited."""

    def wait_child(timeout):
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        return True

    return wait_child
