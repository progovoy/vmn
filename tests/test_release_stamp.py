import pytest
import sys
sys.path.append("{0}/../version_stamp".format(__file__.rsplit('/',2)[0]))

import vmn
import stamp_utils
from test_ver_stamp import _run_vmn_init, _init_app, _stamp_app


def _release_with_stamp(app_name, dry=False):
    cmd = ["release", "--stamp"]
    if dry:
        cmd.append("--dry")
    cmd.append(app_name)
    stamp_utils.VMN_LOGGER = None
    ret, vmn_ctx = vmn.vmn_run(cmd)
    vmn_ctx.vcs.initialize_backend_attrs()
    tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
        app_name, type=stamp_utils.RELATIVE_TO_CURRENT_VCS_POSITION_TYPE
    )
    vmn_ctx.vcs.enhance_ver_info(ver_infos)
    ver_info = None
    if tag_name in ver_infos and ver_infos[tag_name]["ver_info"] is not None:
        ver_info = ver_infos[tag_name]["ver_info"]
    try:
        merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
    except Exception:
        merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}
    return ret, ver_info, merged_dict

  
def test_branch_policy_violation(app_layout, monkeypatch):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")

    app_layout.checkout("feature", create_new=True)

    monkeypatch.setenv("RELEASE_BRANCHES", "main")
    cwd = os.getcwd()
    os.chdir(app_layout.repo_path)
    res = rel.main(["--stamp"])
    os.chdir(cwd)
    assert res == 1
 
  
def test_release_stamp_happy(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")
    prev = app_layout._app_backend.be.changeset()
    err, ver_info, _ = _release_with_stamp(app_layout.app_name)
    assert err == 0
    assert app_layout._app_backend.be.changeset() != prev
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    assert data["prerelease"] == "release"


def test_release_stamp_dry_run(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")
    prev = app_layout._app_backend.be.changeset()
    err, ver_info, _ = _release_with_stamp(app_layout.app_name, dry=True)
    assert err == 0
    assert app_layout._app_backend.be.changeset() == prev
    tags = app_layout.get_all_tags()
    assert f"{app_layout.app_name}_0.0.1" not in tags


def test_release_stamp_push_fail(app_layout, monkeypatch):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")
    prev = app_layout._app_backend.be.changeset()

    def fail_push(self, branch_spec):
        raise RuntimeError("fail")

    monkeypatch.setattr(stamp_utils.GitBackend, "atomic_push", fail_push)
    err, ver_info, _ = _release_with_stamp(app_layout.app_name)
    assert err == 1
    assert app_layout._app_backend.be.changeset() == prev
    tags = app_layout.get_all_tags()
    assert f"{app_layout.app_name}_0.0.1" not in tags


def test_release_stamp_branch_policy(app_layout, capfd):
    _run_vmn_init()
    _, ver_info, params = _init_app(app_layout.app_name)
    policy_conf = {"policies": {"whitelist_release_branches": ["master"]}}
    app_layout.write_conf(params["app_conf_path"], **policy_conf)
    app_layout.checkout("dev", create_new=True)
    _stamp_app(app_layout.app_name, release_mode="patch", prerelease="rc")
    capfd.readouterr()
    err, _, _ = _release_with_stamp(app_layout.app_name)
    captured = capfd.readouterr()
    assert err == 1
    assert captured.err.startswith("[ERROR] Policy: whitelist_release_branches was violated. Refusing to release")


def test_release_stamp_flag_conflict(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    with pytest.raises(SystemExit):
        vmn.vmn_run(["release", "--stamp", "-v", "1.0.0", app_layout.app_name])
