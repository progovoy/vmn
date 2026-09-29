"""The ui's ``exp_rewind`` job action: argv shape and strict input checks."""
import pytest

from vmn_exp.ui.jobs import build_command

V1 = "0.0.1-dev.abc.def"


def test_exp_rewind_builds_the_cli_call():
    cmd, err = build_command("exp_rewind", "my_app", {"verstr": V1, "step": 3})
    assert err is None
    assert cmd == ["vmn-exp", "experiment", "rewind", "my_app", "-v", V1, "--step", "3"]


@pytest.mark.parametrize("step", [None, -1, "3", 1.5, True, [2]])
def test_exp_rewind_rejects_bad_steps(step):
    _, err = build_command("exp_rewind", "my_app", {"verstr": V1, "step": step})
    assert err


@pytest.mark.parametrize("verstr", [None, "", "-rf", "a/b", ".."])
def test_exp_rewind_rejects_bad_verstrs(verstr):
    _, err = build_command("exp_rewind", "my_app", {"verstr": verstr, "step": 1})
    assert err
