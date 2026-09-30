"""`vmn show --from-file` ignores `vmn snapshot` dev records."""
import os

from helpers import _init_app, _run_vmn_init, _show, _snapshot, _stamp_app
from version_stamp.backends.local_file import LocalFileBackend


def _stamp_then_snapshot(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    app_layout.write_conf(params["app_conf_path"], create_snapshots=True)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    with open(os.path.join(app_layout.repo_path, "init.txt"), "a") as f:
        f.write("dirty\n")
    assert _snapshot(app_layout.app_name) == 0


def test_show_from_file_skips_newer_snapshot_record(app_layout, capfd):
    _stamp_then_snapshot(app_layout)
    capfd.readouterr()

    assert _show(app_layout.app_name, from_file=True) == 0

    assert capfd.readouterr().out.strip().splitlines()[-1] == "0.0.1"


def test_latest_stamp_tags_skip_snapshot_record(app_layout):
    _stamp_then_snapshot(app_layout)
    backend = LocalFileBackend(app_layout.repo_path)

    tag_names, _, ver_infos = backend.get_latest_stamp_tags(app_layout.app_name, False)

    assert tag_names == ["test_app_0.0.1"]
    assert ver_infos["test_app_0.0.1"]["ver_info"]["stamping"]["app"]["_version"] == (
        "0.0.1"
    )
