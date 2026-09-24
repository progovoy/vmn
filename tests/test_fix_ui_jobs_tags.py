"""ui job actions for run tags and archiving: argv shape and strict input checks."""
import pytest

from version_stamp.ui.jobs import build_command

V1 = "0.0.1-dev.abc.def"
V2 = "0.0.2-dev.abc.def"


def test_exp_tag_sets_and_removes():
    cmd, err = build_command(
        "exp_tag", "my_app", {"verstr": V1, "set": {"team": "vision", "lr": "3e-4"}, "remove": ["old"]}
    )
    assert err is None
    assert cmd == [
        "vmn", "experiment", "tag", "my_app", V1,
        "team=vision", "lr=3e-4", "--remove", "old",
    ]


def test_exp_tag_remove_only_repeats_the_flag():
    cmd, err = build_command("exp_tag", "my_app", {"verstr": V1, "remove": ["a", "b"]})
    assert err is None
    assert cmd == ["vmn", "experiment", "tag", "my_app", V1, "--remove", "a", "--remove", "b"]


def test_exp_tag_needs_something_to_do():
    _, err = build_command("exp_tag", "my_app", {"verstr": V1})
    assert err
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, "set": {}, "remove": []})
    assert err


@pytest.mark.parametrize("verstr", [None, "", "-rf", "a/b", "..", "x\0y"])
def test_exp_tag_rejects_bad_verstr(verstr):
    _, err = build_command("exp_tag", "my_app", {"verstr": verstr, "set": {"k": "v"}})
    assert err


@pytest.mark.parametrize(
    "key", ["", "-flag", "a=b", "has space", "tab\tkey", "nl\nkey", "k" * 65, "\x07bell"]
)
def test_exp_tag_rejects_bad_keys(key):
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, "set": {key: "v"}})
    assert err
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, "remove": [key]})
    assert err


@pytest.mark.parametrize("value", ["-oops", "line\nbreak", "v" * 257, 3, None, ["x"]])
def test_exp_tag_rejects_bad_values(value):
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, "set": {"k": value}})
    assert err


def test_exp_tag_allows_spaces_inside_values():
    cmd, err = build_command("exp_tag", "my_app", {"verstr": V1, "set": {"desc": "big model v2"}})
    assert err is None
    assert cmd[-1] == "desc=big model v2"


@pytest.mark.parametrize("body", [{"set": "k=v"}, {"remove": "k"}, {"set": {"k": "v"}, "remove": [1]}])
def test_exp_tag_rejects_wrong_shapes(body):
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, **body})
    assert err


def test_exp_tag_bounds_the_number_of_tags():
    many = {f"k{i}": "v" for i in range(101)}
    _, err = build_command("exp_tag", "my_app", {"verstr": V1, "set": many})
    assert err


@pytest.mark.parametrize("action", ["exp_archive", "exp_unarchive"])
def test_exp_archive_commands(action):
    cmd, err = build_command(action, "root/svc", {"verstrs": [V1, V2]})
    assert err is None
    assert cmd == ["vmn", "experiment", action.split("_")[1], "root/svc", V1, V2]


@pytest.mark.parametrize("action", ["exp_archive", "exp_unarchive"])
@pytest.mark.parametrize(
    "verstrs", [None, [], "0.0.1", [V1, "-x"], [V1, "a/b"], [V1, ""], [V1, 7]]
)
def test_exp_archive_rejects_bad_verstrs(action, verstrs):
    _, err = build_command(action, "my_app", {"verstrs": verstrs})
    assert err


def test_exp_archive_bounds_the_batch():
    _, err = build_command("exp_archive", "my_app", {"verstrs": [f"0.0.{i}" for i in range(501)]})
    assert err
    cmd, err = build_command("exp_archive", "my_app", {"verstrs": [f"0.0.{i}" for i in range(500)]})
    assert err is None and len(cmd) == 504
