"""The last-known-version writer is not a `_write_version_to_<backend>` target."""
import yaml

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from version_stamp.stamping.base import IVersionsStamper


def _stamped(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0


def test_vmn_version_file_is_not_a_backend_dispatch_target(app_layout):
    _stamped(app_layout)
    reset_logger()
    vcs = vmn_run(["show", app_layout.app_name])[1].vcs

    assert vcs._version_backend_handler("_write_version_to_", "vmn_version_file") is None


def test_stamp_with_an_injected_vmn_version_file_backend_skips_it(
    app_layout, monkeypatch
):
    _stamped(app_layout)
    original = IVersionsStamper.update_attrs_from_app_conf_file

    def inject(self):
        original(self)
        self.version_backends = {"vmn_version_file": {}}

    monkeypatch.setattr(IVersionsStamper, "update_attrs_from_app_conf_file", inject)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "change")

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")

    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    with open(params["version_file_path"]) as f:
        assert yaml.safe_load(f)["version_to_stamp_from"] == "0.0.2"
