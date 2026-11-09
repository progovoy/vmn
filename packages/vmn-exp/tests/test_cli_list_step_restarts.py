"""``vmn-exp list`` marks a metric whose steps went back without a rewind,
from the index row's ``step_restarts``: ``best=0.989 (steps went back)``."""
from exp_helpers import _bootstrap, _exp
from vmn_exp.sdk import start_run


def _run(app_layout, steps):
    with start_run(app_layout.app_name) as run:
        for i, step in enumerate(steps):
            run.log_metric("best", 0.5 + i / 1000, step=step)
        return run.id


def test_cli_list_marks_a_metric_whose_steps_went_back(app_layout, capfd):
    _bootstrap(app_layout)
    went_back, rising = _run(app_layout, [0, 1, 2, 0, 1]), _run(app_layout, [0, 1, 2])
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list") == 0
    lines = capfd.readouterr().out.splitlines()
    assert "best=0.504 (steps went back)" in next(line for line in lines if went_back in line)
    assert "steps went back" not in next(line for line in lines if rising in line)
