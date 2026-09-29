"""`vmn snapshot` create/list/show/note and ref resolution (resurrected from
the pre-d4954f8 tests/test_snapshot.py, adjusted for thin records)."""
import os

import yaml

from helpers import (
    DEV_VERSION_RE,
    _bootstrap,
    _init_app,
    _run_vmn_init,
    _snapshot,
    _stamp_app,
    extract_dev_verstr,
)


def _dirty(app_layout, filename, content):
    app_layout.write_file_commit_and_push("test_repo_0", filename, "initial")
    with open(os.path.join(app_layout.repo_path, filename), "w") as f:
        f.write(content)


def _create(app_layout, capfd, **kwargs):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, **kwargs) == 0
    return extract_dev_verstr(capfd.readouterr().out)


def _make_two_snapshots(app_layout, capfd):
    """Create two distinct dev snapshots; return (v1_oldest, v2_newest)."""
    verstrs = []
    for i, content in enumerate(["first change", "second change"]):
        _dirty(app_layout, f"s{i}.txt", content)
        verstrs.append(_create(app_layout, capfd, note=f"snap {i}"))
    return verstrs


def _show(app_layout, capfd, **kwargs):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="show", **kwargs)
    captured = capfd.readouterr()
    return ret, captured


def test_snapshot_create_clean_tree_message_on_stderr(app_layout, capfd):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    captured = capfd.readouterr()
    assert "No local changes" not in captured.out
    assert "No local changes to snapshot (working tree is clean)" in captured.err


def test_snapshot_create_and_list(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "snap_file.txt", "snapshot content")
    verstr = _create(app_layout, capfd, note="test note")
    assert verstr is not None and verstr.startswith("0.0.1-dev.")

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert verstr in out
    assert "test note" in out
    assert "[1]" in out
    assert "ago)" in out

    ret, captured = _show(app_layout, capfd, version=verstr)
    assert ret == 0
    assert "base_version" in captured.out
    assert "code:" in captured.out
    assert "--- Working tree patch ---" in captured.out
    assert "snapshot content" in captured.out


def test_snapshot_latest(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "f1.txt", "change A")
    verstr1 = _create(app_layout, capfd, note="first")
    with open(os.path.join(app_layout.repo_path, "f1.txt"), "w") as f:
        f.write("change B")
    verstr2 = _create(app_layout, capfd, note="second")
    assert verstr1 != verstr2

    ret, captured = _show(app_layout, capfd, latest=True)
    assert ret == 0
    assert verstr2 in captured.out
    assert "second" in captured.out


def test_snapshot_prefix_match(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "f1.txt", "prefix content")
    verstr = _create(app_layout, capfd)
    ret, captured = _show(app_layout, capfd, version=verstr[:15])
    assert ret == 0
    assert verstr in captured.out


def test_snapshot_note_update(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "note_file.txt", "content")
    verstr = _create(app_layout, capfd, note="original note")
    assert _snapshot(
        app_layout.app_name, action="note", version=verstr, note="updated note"
    ) == 0
    ret, captured = _show(app_layout, capfd, version=verstr)
    assert ret == 0
    assert "updated note" in captured.out


def test_snapshot_content_addressable(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "addr.txt", "deterministic content")
    assert _create(app_layout, capfd) == _create(app_layout, capfd)


def test_snapshot_metadata_hooks(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "dirty_file.txt", "dirty content")
    verstr = _create(app_layout, capfd, meta=["lr=3e-4", "epochs=100"])
    ret, captured = _show(app_layout, capfd, version=verstr)
    assert ret == 0
    assert "user_meta" in captured.out and "3e-4" in captured.out

    with open(os.path.join(app_layout.repo_path, "dirty_file.txt"), "w") as f:
        f.write("different dirty content")
    _create(app_layout, capfd, meta=["lr=1e-5", "epochs=200"])

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", filter_args=["lr=3e-4"]) == 0
    filtered = capfd.readouterr().out
    assert "lr=3e-4" in filtered and "lr=1e-5" not in filtered

    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list") == 0
    listed = capfd.readouterr().out
    assert "lr=3e-4" in listed and "lr=1e-5" in listed


def test_snapshot_metadata_file(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "dirty_file.txt", "dirty content")
    meta_path = os.path.join(app_layout.repo_path, "meta.yml")
    with open(meta_path, "w") as f:
        yaml.dump({"model": {"type": "transformer", "layers": 12}, "dataset": "imagenet"}, f)

    verstr = _create(app_layout, capfd, meta_file=meta_path)
    ret, captured = _show(app_layout, capfd, version=verstr)
    assert ret == 0
    for word in ("user_meta", "transformer", "layers", "imagenet"):
        assert word in captured.out


def test_snapshot_actions_require_init(app_layout, capfd):
    name = app_layout.app_name
    some = "0.0.1-dev.abc1234.def5678"
    assert _snapshot(name, action="list") != 0
    assert _snapshot(name, action="show", version=some) != 0
    assert _snapshot(name, action="diff", version=some, to_version="current") != 0
    assert _snapshot(name, action="export", version=some, output="/tmp/x") != 0

    capfd.readouterr()
    assert _snapshot(name) != 0
    captured = capfd.readouterr()
    combined = captured.out + captured.err
    assert "vmn stamp" in combined or "vmn init" in combined


def test_snapshot_list_skips_legacy_stamp_snapshots(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_snapshots": True,
        "deps": {"../": {"test_repo_0": {
            "vcs_type": app_layout.be_type,
            "remote": app_layout._app_backend.be.remote(),
        }}},
        "extra_info": False,
    }
    app_layout.write_conf(params["app_conf_path"], **conf)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert os.path.isdir(
        os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "snapshots")
    )

    _dirty(app_layout, "another.txt", "dirty again")
    verstr = _create(app_layout, capfd)
    assert verstr is not None
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list") == 0
    assert verstr in capfd.readouterr().out


def test_snapshot_show_defaults_to_latest(app_layout, capfd):
    _bootstrap(app_layout)
    v1, v2 = _make_two_snapshots(app_layout, capfd)
    ret, captured = _show(app_layout, capfd)
    assert ret == 0
    assert v2 in captured.out
    assert v1 not in captured.out


def test_snapshot_create_stdout_last_line_is_verstr(app_layout, capfd):
    _bootstrap(app_layout)
    _dirty(app_layout, "only.txt", "dirty")
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, note="x") == 0
    lines = [ln for ln in capfd.readouterr().out.strip().split("\n") if ln.strip()]
    assert DEV_VERSION_RE.match(lines[-1].strip())


def test_snapshot_at_index_addressing(app_layout, capfd):
    _bootstrap(app_layout)
    v1, v2 = _make_two_snapshots(app_layout, capfd)
    assert v1 in _show(app_layout, capfd, version="@1")[1].out
    assert v2 in _show(app_layout, capfd, version="@2")[1].out


def test_snapshot_ambiguous_prefix_lists_candidates(app_layout, capfd):
    _bootstrap(app_layout)
    v1, v2 = _make_two_snapshots(app_layout, capfd)
    ret, captured = _show(app_layout, capfd, version="0.0.1-dev.")
    assert ret == 1
    assert "mbiguous" in captured.err
    assert v1 in captured.err and v2 in captured.err
