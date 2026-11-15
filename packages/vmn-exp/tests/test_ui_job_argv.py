"""ui/job_argv.py: every request-derived argv token of a ui job is built here,
an option always as the single token ``--flag=value``."""
import pytest

from vmn_exp.ui.job_argv import ACTIONS, EMITTED, LONG_FLAGS, SWITCHES, opt, positional, switch


def test_opt_renders_one_token():
    assert opt("--version", "1.0.0") == "--version=1.0.0"
    assert opt("--metrics", "loss=-1") == "--metrics=loss=-1"


@pytest.mark.parametrize("value", [7, True, None, ["-x"], {"a": 1}, b"x"])
def test_opt_refuses_non_str_value(value):
    with pytest.raises(ValueError):
        opt("--note", value)


@pytest.mark.parametrize("flag", ["-v", "--attach", "--note ", "note", "--output"])
def test_opt_refuses_unknown_flag(flag):
    with pytest.raises(ValueError):
        opt(flag, "x")


@pytest.mark.parametrize("value", ["-x", "--", "-", "", "--attach=/etc/passwd", 7, None, ["a"]])
def test_positional_refuses_dash_leading_empty_and_non_str(value):
    with pytest.raises(ValueError):
        positional(value)


def test_positional_keeps_a_plain_value():
    assert positional("desc=big model v2") == "desc=big model v2"


def test_note_starting_with_dash_is_one_token():
    assert opt("--note", "- lowered lr") == "--note=- lowered lr"
    assert opt("--note", "--") == "--note=--"


def test_switch_only_takes_a_known_switch():
    assert switch("--dry-run") == "--dry-run"
    with pytest.raises(ValueError):
        switch("--force")


def test_emitted_table_covers_every_action():
    assert set(EMITTED) == set(ACTIONS)
    emitted = {flag for flags in EMITTED.values() for flag in flags}
    assert emitted == set(LONG_FLAGS) | set(SWITCHES)
