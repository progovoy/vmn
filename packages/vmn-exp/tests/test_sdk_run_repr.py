"""The run object's repr: one line in a REPL or a log, a small HTML block in a
notebook (plan 43 F18). Both read only what the run holds in memory."""
import os
from vmn_exp.sdk import run_repr
from vmn_exp.sdk.ranks import NoOpRun
from vmn_exp.sdk.run import Run
from vmn_exp.core.real_io import RealClock, RealHost, RealRandom

APP = "my_app"
VERSTR = "0.1.2-dev.3f9a.r4"


def test_the_text_repr_names_the_app_the_id_the_name_and_the_state():
    text = run_repr.text(APP, VERSTR, "baseline", "running", None)

    assert text == '<Run my_app 0.1.2-dev.3f9a.r4 "baseline" running>'


def test_a_finished_run_reads_finished_with_its_exit_code():
    text = run_repr.text(APP, VERSTR, "baseline", "finished", 1)

    assert text == '<Run my_app 0.1.2-dev.3f9a.r4 "baseline" finished exit 1>'


def test_a_run_without_a_name_has_no_empty_quotes():
    text = run_repr.text(APP, VERSTR, None, "running", None)

    assert text == "<Run my_app 0.1.2-dev.3f9a.r4 running>"


def test_the_html_repr_escapes_the_run_name():
    html = run_repr.html(APP, VERSTR, "<script>", "running", None)

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_the_html_repr_gives_the_show_command_for_this_run():
    html = run_repr.html(APP, VERSTR, "baseline", "finished", 0)

    assert f"vmn-exp show {APP} -v {VERSTR}" in html
    assert "finished" in html
    assert "exit 0" in html


def test_a_noop_run_says_it_records_nothing():
    disabled = repr(NoOpRun(APP, disabled=True))
    secondary = repr(NoOpRun(APP, rank=3))

    assert "records nothing" in disabled and "disabled" in disabled
    assert "records nothing" in secondary and "rank 3" in secondary


class _AccessRecorder:
    """A storage stand-in that records every attribute read on it."""

    def __init__(self):
        object.__setattr__(self, "reads", [])

    def __getattr__(self, name):
        self.reads.append(name)
        raise AttributeError(name)


def test_repr_of_an_open_run_delegates_and_reads_no_storage():
    storage = _AccessRecorder()
    run = Run(storage, APP, VERSTR, 60, name="baseline", env=os.environ, install_hooks=None, clock=RealClock(), host=RealHost(), random=RealRandom())
    storage.reads.clear()  # the baseline is taken after construction

    text = repr(run)
    html = run._repr_html_()

    assert storage.reads == []
    assert text == run_repr.text(APP, VERSTR, "baseline", "running", None)
    assert html == run_repr.html(APP, VERSTR, "baseline", "running", None)
