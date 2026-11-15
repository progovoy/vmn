"""``sys.exit(N)`` is noted, so a run left open at exit reads failed with N.

``SystemExit`` never reaches ``sys.excepthook``, so without the note a job
that ends in ``sys.exit(main())`` with a run still open read as succeeded.
"""
import threading
from types import SimpleNamespace

import pytest

from vmn_exp.sdk.exit_code import ExitCodeNote


class FakeSys:
    def __init__(self):
        self.calls = []
        self.exit = self._exit

    def _exit(self, *args):
        self.calls.append(args)
        raise SystemExit(*args)


def _exit(fake_sys, *args):
    with pytest.raises(SystemExit):
        fake_sys.exit(*args)


def test_install_records_the_code_and_still_calls_the_previous_exit():
    fake_sys = FakeSys()
    note = ExitCodeNote()
    note.install(fake_sys)

    _exit(fake_sys, 3)

    assert note.noted() == 3
    assert fake_sys.calls == [(3,)]


def test_nothing_noted_reads_zero():
    note = ExitCodeNote()
    note.install(FakeSys())

    assert note.noted() == 0


def test_install_twice_wraps_once():
    fake_sys = FakeSys()
    note = ExitCodeNote()
    note.install(fake_sys)
    wrapped = fake_sys.exit

    note.install(fake_sys)
    _exit(fake_sys, 2)

    assert fake_sys.exit is wrapped
    assert fake_sys.calls == [(2,)]


@pytest.mark.parametrize("args, expected", [((), 0), ((None,), 0), (("bad input",), 1), ((7,), 7)])
def test_no_argument_and_none_count_as_zero_and_a_message_as_one(args, expected):
    fake_sys = FakeSys()
    note = ExitCodeNote()
    note.install(fake_sys)

    _exit(fake_sys, *args)

    assert note.noted() == expected


def test_clear_forgets_a_swallowed_exit():
    fake_sys = FakeSys()
    note = ExitCodeNote()
    note.install(fake_sys)
    _exit(fake_sys, 4)

    note.clear()

    assert note.noted() == 0


def test_a_sys_exit_in_a_worker_thread_is_not_noted():
    """It ends only that thread, never the process: the exit code stays 0."""
    fake_sys = FakeSys()
    note = ExitCodeNote()
    note.install(fake_sys)
    worker = threading.Thread(target=lambda: _exit(fake_sys, 5))
    worker.start()
    worker.join()

    assert note.noted() == 0
    assert fake_sys.calls == [(5,)]


def test_install_chains_to_the_exit_that_was_current():
    seen = []
    fake_sys = SimpleNamespace(exit=lambda *args: seen.append(args))
    note = ExitCodeNote()
    note.install(fake_sys)

    fake_sys.exit(6)

    assert seen == [(6,)]
    assert note.noted() == 6
