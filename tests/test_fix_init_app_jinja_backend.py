"""`vmn init-app` on an app whose conf (committed beforehand) has a generic
version backend failed: the backend's template data runs git-cliff from the
previous version's tag, which init-app has not created yet. The vmn_exp app
of this repo hit it on its first release."""
import glob
import os
import shutil

import pytest
import yaml

from version_stamp.core.constants import _VMN_VERSION_REGEX

from helpers import _init_app, _run_vmn_init, _stamp_app


def _backend(path):
    return {
        "generic_selectors": [
            {
                "paths_section": [{"input_file_path": path, "output_file_path": path}],
                "selectors_section": [
                    {"regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                     "regex_sub": r"\1{{version}}"},
                ],
            }
        ]
    }


@pytest.mark.skipif(shutil.which("git-cliff") is None, reason="needs git-cliff")
def test_init_app_with_a_committed_generic_backend_conf(app_layout):
    _run_vmn_init()
    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "0.0.0"})
    )
    conf_path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    os.makedirs(os.path.dirname(conf_path), exist_ok=True)
    app_layout.write_conf(conf_path, version_backends=_backend("in.txt"))

    ret, _, _ = _init_app(app_layout.app_name)
    assert ret == 0
    assert glob.glob(os.path.join(app_layout.repo_path, "*.tmp.jinja2")) == []

    err, _, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    with open(os.path.join(app_layout.repo_path, "in.txt")) as f:
        assert yaml.safe_load(f)["version"] == "0.1.0"
