"""A stamp or init-app that failed while writing a generic_selectors backend
left its `*.tmp.jinja2` files behind, and a failed init-app also left the new
app's untracked last_known_app_version.yml (the revert only restores tracked
files) — the vmn_exp app of this repo hit both on its first release."""
import os
import subprocess

import yaml
from helpers import _init_app, _run_vmn_init, _stamp_app, reset_logger, vmn_run
from version_stamp.core.constants import _VMN_VERSION_REGEX

BROKEN_SUB = r"\1{{version"  # renders as an unclosed jinja expression


def _backend(regex_sub):
    return {
        "generic_selectors": [
            {
                "paths_section": [{"input_file_path": "in.txt", "output_file_path": "in.txt"}],
                "selectors_section": [
                    {"regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                     "regex_sub": regex_sub},
                ],
            }
        ]
    }


def _setup(app_layout, regex_sub):
    _run_vmn_init()
    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "0.0.0"})
    )
    conf_path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    app_layout.write_conf(conf_path, version_backends=_backend(regex_sub))
    return conf_path


def _status(app_layout):
    return subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=app_layout.repo_path, check=True, capture_output=True, text=True,
    ).stdout


def test_a_failed_init_app_leaves_the_tree_clean(app_layout):
    _setup(app_layout, BROKEN_SUB)

    reset_logger()
    ret, _ = vmn_run(["init-app", app_layout.app_name])  # _init_app needs a success

    assert ret != 0
    assert _status(app_layout) == ""


def test_a_failed_stamp_leaves_the_tree_clean(app_layout):
    conf_path = _setup(app_layout, r"\1{{version}}")
    assert _init_app(app_layout.app_name)[0] == 0
    app_layout.write_conf(conf_path, version_backends=_backend(BROKEN_SUB))

    err, _, _ = _stamp_app(app_layout.app_name, "patch")

    assert err != 0
    assert _status(app_layout) == ""
