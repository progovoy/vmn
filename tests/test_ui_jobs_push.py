"""The ui's ``exp_push`` job action: argv shape and strict input checks."""
import pytest

from vmn_exp.ui.jobs import build_command

V1 = "0.0.1-dev.abc.def"
V2 = "0.0.1-dev.abc.def.laptop"


def test_exp_push_all_runs():
    cmd, err = build_command("exp_push", "my_app", {})
    assert err is None
    assert cmd == ["vmn-exp", "experiment", "push", "my_app"]


def test_exp_push_named_runs():
    cmd, err = build_command("exp_push", "my_app", {"verstrs": [V1, V2]})
    assert err is None
    assert cmd == ["vmn-exp", "experiment", "push", "my_app", "-v", V1, "-v", V2]


@pytest.mark.parametrize("verstrs", ["x", [None], ["-rf"], ["a/b"], [".."]])
def test_exp_push_rejects_bad_verstrs(verstrs):
    _, err = build_command("exp_push", "my_app", {"verstrs": verstrs})
    assert err
