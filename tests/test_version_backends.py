import json
import os

import toml
import yaml

from version_stamp.core.constants import _VMN_VERSION_REGEX

from helpers import _init_app, _run_vmn_init, _stamp_app


def test_version_backends_generic_jinja(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = "VERSION: {{version}}\n" "Custom: {{k1}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_jinja = {
        "generic_jinja": [
            {
                "input_file_path": "f1.jinja2",
                "output_file_path": "jinja_out.txt",
                "custom_keys_path": "custom.yml",
            },
        ]
    }

    conf = {"version_backends": generic_jinja}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.2"
        assert data["Custom"] == 5


def test_version_backends_generic_selectors(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in2.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                        "custom_keys_path": "custom.yml",
                    },
                    {
                        "input_file_path": "in2.txt",
                        "output_file_path": "in2.txt",
                    },
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                    {"regex_selector": "(Custom: )([0-9]+)", "regex_sub": r"\1{{k1}}"},
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")
    opath2 = os.path.join(app_layout._repos["test_repo_0"]["path"], "in2.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] == 5

    with open(opath2, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] is None


def test_version_backends_generic_selectors_no_custom_keys(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2-x"
        assert data["Custom"] == 3


def test_version_backends_generic_selectors_regex_vars(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                        "custom_keys_path": "custom.yml",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": "(version: )({{VMN_VERSION_REGEX}})",
                        "regex_sub": r"\1{{version}}",
                    },
                    {"regex_selector": "(Custom: )([0-9]+)", "regex_sub": r"\1{{k1}}"},
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] == 5


def test_generic_selectors_multiple_apps_same_file_same_diff(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    second_app = f"{app_layout.app_name}_2"
    _, _, params2 = _init_app(second_app)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_conf(params2["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2-x"
        assert data["Custom"] == 3


def test_generic_selectors_multiple_apps_same_file_diff(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    second_app = f"{app_layout.app_name}_2"
    _, _, params2 = _init_app(second_app)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "major")
    assert ver_info2["stamping"]["app"]["_version"] == "1.0.0"
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_conf(params2["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "1.0.1"
    assert err == 0

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.3"
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.3-x"
        assert data["Custom"] == 3


def test_version_backends_cargo(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "Cargo.toml",
        toml.dumps({"package": {"name": "test_app", "version": "some ignored string"}}),
    )

    conf = {
        "version_backends": {"cargo": {"path": "Cargo.toml"}},
        "deps": {
            "../": {
                "test_repo_0": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["cargo"]["path"]
    )

    with open(full_path, "r") as f:
        data = toml.load(f)
        assert data["package"]["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_version_backends_poetry(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "pyproject.toml",
        toml.dumps(
            {"tool": {"poetry": {"name": "test_app", "version": "some ignored string"}}}
        ),
    )

    conf = {
        "version_backends": {"poetry": {"path": "pyproject.toml"}},
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["poetry"]["path"]
    )

    with open(full_path, "r") as f:
        data = toml.load(f)
        assert data["tool"]["poetry"]["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_version_backends_pep621(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "pyproject.toml",
        toml.dumps(
            {"project": {"name": "test_app", "version": "some ignored string"}}
        ),
    )

    conf = {
        "version_backends": {"pep621": {"path": "pyproject.toml"}},
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["pep621"]["path"]
    )

    with open(full_path, "r") as f:
        data = toml.load(f)
        assert data["project"]["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_version_backends_npm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "package.json",
        json.dumps({"name": "test_app", "version": "some ignored string"}),
    )

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "version_backends": {"npm": {"path": "package.json"}},
        "deps": {
            "../": {
                "test_repo_0": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
        "extra_info": False,
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["npm"]["path"]
    )

    with open(full_path, "r") as f:
        data = json.load(f)
        assert data["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_version_backends_generic_selectors_jinja_file_with_jinja_expr(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    # Simulate a file that is a jinja template with a jinja expression that will fail
    jinja_expr_content = (
        'INTEGRATION_LAB: "{{ lookup(\'env\', \'INTEGRATION_LAB\') | default(false) }}"\n'
        'version: 1.0.2\nCustom: 3\n'
    )
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        jinja_expr_content,
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){_VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    capfd.readouterr()
    # Run the stamp and check for nonzero error code and error message in stderr
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    captured = capfd.readouterr()
    assert ("lookup" not in captured.err and "undefined" not in captured.err)

    assert err == 0

    # Check the output file: version should be replaced, lookup should be preserved
    with open(opath, "r") as f:
        content = f.read()
        assert 'INTEGRATION_LAB: "{{ lookup(\'env\', \'INTEGRATION_LAB\') | default(false) }}"' in content
        assert 'version: 0.0.2' in content
