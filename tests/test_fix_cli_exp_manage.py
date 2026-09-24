"""`vmn exp create/run --name`, `vmn exp tag`, `vmn exp archive/unarchive`."""
import re

from helpers import _bootstrap, _exp, _storage

from version_stamp.core.experiment_log import experiment_row

_ROW_RE = re.compile(r"^\s*\[(\d+)\]\s+(\S+)")


def _create(app_layout, *extra):
    assert _exp(app_layout.app_name, extra_args=list(extra)) == 0
    return _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]


def _row(app_layout, verstr):
    st, app = _storage(app_layout), app_layout.app_name
    return experiment_row(1, st.load_metadata(app, verstr), st.load_merged_log(app, verstr))


def _list(app_layout, capfd, *extra):
    capfd.readouterr()
    assert _exp(app_layout.app_name, action="list", extra_args=list(extra)) == 0
    out = capfd.readouterr().out
    return out, [m.group(2) for m in map(_ROW_RE.match, out.splitlines()) if m]


def test_create_with_a_name_stores_and_lists_it(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = _create(app_layout, "--name", "baseline-v1")

    assert _row(app_layout, verstr)["name"] == "baseline-v1"
    out, _ = _list(app_layout, capfd)
    assert "baseline-v1" in out


def test_run_with_a_name(app_layout):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name, action="run", extra_args=["--name", "r1"],
                run_cmd=["true"]) == 0
    verstr = _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]
    assert _row(app_layout, verstr)["name"] == "r1"


def test_tag_sets_and_removes_tags(app_layout):
    _bootstrap(app_layout)
    verstr = _create(app_layout)
    app = app_layout.app_name

    assert _exp(app, action="tag", extra_args=[verstr, "stage=dev", "owner=ann"]) == 0
    assert _exp(app, action="tag", extra_args=[verstr, "stage=prod", "--remove", "owner"]) == 0

    assert _row(app_layout, verstr)["tags"] == {"stage": "prod"}


def test_tag_accepts_version_flag_and_values_with_equals(app_layout):
    _bootstrap(app_layout)
    verstr = _create(app_layout)

    # argparse binds positionals before the first flag: tags come first.
    assert _exp(app_layout.app_name, action="tag",
                extra_args=["expr=a=b", "-v", verstr]) == 0

    assert _row(app_layout, verstr)["tags"] == {"expr": "a=b"}


def test_tag_a_finished_run(app_layout):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name, action="run", run_cmd=["true"]) == 0
    verstr = _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]

    assert _exp(app_layout.app_name, action="tag", extra_args=[verstr, "k=v"]) == 0
    assert _row(app_layout, verstr)["tags"] == {"k": "v"}


def test_tag_needs_a_run_and_a_change(app_layout):
    _bootstrap(app_layout)
    verstr = _create(app_layout)
    app = app_layout.app_name

    assert _exp(app, action="tag", extra_args=["k=v"]) == 1
    assert _exp(app, action="tag", extra_args=[verstr]) == 1
    assert _exp(app, action="tag", extra_args=[verstr, "=v"]) == 1


def test_archive_hides_runs_from_list_until_unarchived(app_layout, capfd):
    _bootstrap(app_layout)
    first, second, third = (_create(app_layout) for _ in range(3))
    app = app_layout.app_name

    assert _exp(app, action="archive", extra_args=[first, second]) == 0
    assert _row(app_layout, first)["archived"] is True
    _, shown = _list(app_layout, capfd)
    assert shown == [third]

    out, shown = _list(app_layout, capfd, "--archived")
    assert shown == [first, second, third]
    assert "archived" in out

    assert _exp(app, action="unarchive", extra_args=[second]) == 0
    _, shown = _list(app_layout, capfd)
    assert shown == [second, third]


def test_archive_of_an_unknown_run_fails(app_layout):
    _bootstrap(app_layout)
    _create(app_layout)
    assert _exp(app_layout.app_name, action="archive", extra_args=["nope-dev.x"]) == 1


def test_stray_positionals_are_refused_by_other_actions(app_layout):
    _bootstrap(app_layout)
    _create(app_layout)
    assert _exp(app_layout.app_name, action="list", extra_args=["extra"]) == 1


def test_prune_treats_archived_runs_like_any_finished_run(app_layout):
    _bootstrap(app_layout)
    older, newer = _create(app_layout), _create(app_layout)
    app = app_layout.app_name
    assert _exp(app, action="archive", extra_args=[older]) == 0

    assert _exp(app, action="prune", keep=1) == 0

    assert _storage(app_layout).list_verstrs(app) == [newer]
