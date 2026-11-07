"""Plan 32 F1: ``vmn-exp compare`` and ``vmn-exp diff`` name each value's
summary policy but ``last`` — ``0.2 (min)`` — and say when two runs'
summaries of one metric differ, never comparing them silently."""
from exp_helpers import _bootstrap, _exp
from test_metric_policy import _run, _seed, _write_schema


def _line(capfd, start):
    return next(ln for ln in capfd.readouterr().out.splitlines() if ln.startswith(start))


def test_compare_names_the_policies_and_says_they_differ(app_layout, capfd):
    own, plain = _seed(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="compare", version=[own, plain]) == 0
    line = _line(capfd, "loss")
    assert line.split()[1:4] == ["0.2", "(min)", "0.9"], line
    assert line.rstrip().endswith("summaries differ: min vs last"), line


def test_compare_of_one_policy_names_it_without_a_warning(app_layout, capfd):
    _bootstrap(app_layout)
    a, b = _run(app_layout, [1.0, 0.3, 0.9]), _run(app_layout, [1.0, 0.25])
    _write_schema(app_layout, {"loss": {"goal": "min"}})
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="compare", version=[a, b]) == 0
    line = _line(capfd, "loss")
    assert line.split()[1:5] == ["0.3", "(min)", "0.25", "(min)"], line
    assert "differ" not in line


def test_compare_of_last_values_names_none(app_layout, capfd):
    _bootstrap(app_layout)
    a, b = _run(app_layout, [1.0, 0.3]), _run(app_layout, [1.0, 0.25])
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="compare", version=[a, b]) == 0
    assert _line(capfd, "loss").split()[1:] == ["0.3", "0.25"]


def test_diff_names_the_policies_and_says_they_differ(app_layout, capfd):
    own, plain = _seed(app_layout)
    capfd.readouterr()
    _exp(app_layout.app_name, action="diff", version=[own, plain])
    line = _line(capfd, "metrics:")
    assert "loss 0.2 (min) -> 0.9 (summaries differ: min vs last)" in line, line


def test_diff_of_one_policy_names_it(app_layout, capfd):
    _bootstrap(app_layout)
    a, b = _run(app_layout, [1.0, 0.3, 0.9]), _run(app_layout, [1.0, 0.25])
    _write_schema(app_layout, {"loss": {"goal": "min"}})
    capfd.readouterr()
    _exp(app_layout.app_name, action="diff", version=[a, b])
    line = _line(capfd, "metrics:")
    assert "loss 0.3 (min) -> 0.25 (min)" in line and "differ" not in line, line
