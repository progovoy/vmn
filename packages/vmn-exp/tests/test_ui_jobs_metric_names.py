"""ui job actions: a metric name is never an option of the `vmn-exp` argv.

`--metrics` takes any number of values, so a name starting with `-` would end
the list and parse as a flag of its own (`--attach=/etc/passwd`).
"""
import pytest

from vmn_exp.ui.jobs import _metric_args, build_command

V1 = "0.0.1-dev.abc.def"
OPTION_LIKE = ["--attach", "-f/etc/passwd", "--dry-run", "-", "--", "-loss"]


@pytest.mark.parametrize("name", OPTION_LIKE)
def test_metric_args_rejects_option_like_names(name):
    args, err = _metric_args({name: "/etc/passwd"})
    assert args is None
    assert err == f"Invalid metric name '{name}'"


@pytest.mark.parametrize("name", OPTION_LIKE)
def test_exp_create_rejects_option_like_metric_names(name):
    cmd, err = build_command("exp_create", "my_app", {"metrics": {name: "/etc/passwd"}})
    assert cmd is None
    assert err == f"Invalid metric name '{name}'"


@pytest.mark.parametrize("name", OPTION_LIKE)
def test_exp_add_rejects_option_like_metric_names(name):
    cmd, err = build_command(
        "exp_add", "my_app", {"verstr": V1, "metrics": {"loss": 0.1, name: 1}}
    )
    assert cmd is None
    assert err == f"Invalid metric name '{name}'"


def test_metric_names_may_contain_a_dash_after_the_first_character():
    args, err = _metric_args({"val-loss": 0.1})
    assert err is None
    assert args == ["--metrics", "val-loss=0.1"]


def test_option_like_metric_values_stay_values():
    args, err = _metric_args({"delta": "-1", "flag": "--attach"})
    assert err is None
    assert args == ["--metrics", "delta=-1", "flag=--attach"]
