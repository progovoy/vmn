"""The three distributions' declarations (packages/*/pyproject.toml).

See docs/packaging.md. `pip install x[typo]` only warns, and a stale pin only
bites after a release, so these are checked here rather than discovered by users.
"""
import pathlib

import pytest
import toml

ROOT = pathlib.Path(__file__).resolve().parent.parent
DISTS = ("vmn", "vmn-exp-sdk", "vmn-exp")
HEAVY = ("torch", "tensorflow", "keras", "lightning", "jax")


def _project(dist):
    return toml.load(ROOT / "packages" / dist / "pyproject.toml")["project"]


def _requirements(dist):
    project = _project(dist)
    extras = project.get("optional-dependencies", {})
    return project.get("dependencies", []) + [r for reqs in extras.values() for r in reqs]


@pytest.mark.parametrize("dist", DISTS)
def test_each_distribution_is_named_after_its_folder(dist):
    assert _project(dist)["name"] == dist


def test_the_exp_packages_share_one_version_and_pin_each_other():
    sdk_version = _project("vmn-exp-sdk")["version"]
    assert _project("vmn-exp")["version"] == sdk_version
    assert f"vmn-exp-sdk=={sdk_version}" in _project("vmn-exp")["dependencies"]


def test_vmn_exp_depends_on_vmn_below_its_next_major():
    [pin] = [r for r in _project("vmn-exp")["dependencies"] if r.startswith("vmn<")
             or r.startswith("vmn>")]
    assert "<" in pin


def test_vmn_depends_on_neither_exp_package():
    assert not [r for r in _project("vmn")["dependencies"] if r.startswith("vmn-exp")]


def test_the_sdk_needs_only_yaml_and_filelock():
    names = sorted(r.split(">")[0].split("=")[0] for r in _project("vmn-exp-sdk")["dependencies"])
    assert names == ["PyYAML", "filelock"]


@pytest.mark.parametrize("dist, extras", [
    ("vmn", {"changelog"}),
    ("vmn-exp-sdk", {"s3", "sysmetrics"}),
    ("vmn-exp", {"ui", "s3", "sysmetrics", "mlflow"}),
])
def test_documented_extras_exist(dist, extras):
    assert extras <= set(_project(dist).get("optional-dependencies", {}))


@pytest.mark.parametrize("dist", DISTS)
def test_no_distribution_pulls_in_a_training_framework(dist):
    # autolog patches the framework the user already has.
    heavy = [r for r in _requirements(dist) if r.lower().startswith(HEAVY)]
    assert heavy == []


def test_gitpython_uses_a_range_not_an_exact_pin():
    # An exact pin fights the resolver when mlflow/dvc constrain GitPython too.
    [git] = [r for r in _project("vmn")["dependencies"] if r.lower().startswith("gitpython")]
    assert "==" not in git and ">=" in git


def test_the_commands_and_the_plugin_are_declared():
    assert set(_project("vmn")["scripts"]) >= {"vmn"}
    assert _project("vmn-exp")["scripts"] == {"vmn-exp": "vmn_exp.cli.main:main"}
    plugins = _project("vmn-exp")["entry-points"]["vmn.plugins"]
    assert plugins == {"snapshot": "vmn_exp.cli.plugin:register_snapshot"}


def test_the_s3_import_error_names_the_extra_to_install():
    s3_base = ROOT / "packages/vmn-exp-sdk/src/vmn_exp/storage/s3_base.py"
    assert "vmn-exp-sdk[s3]" in s3_base.read_text()


def _selectors(app):
    import yaml

    conf = yaml.safe_load((ROOT / ".vmn" / app / "conf.yml").read_text())["conf"]
    [backend] = conf["version_backends"]["generic_selectors"]
    return backend


def _stamp_with(app, verstr):
    """``{path: text}`` after applying *app*'s selectors as `vmn stamp` does."""
    import re

    backend = _selectors(app)
    out = {}
    for paths in backend["paths_section"]:
        assert paths["input_file_path"] == paths["output_file_path"]
        path = paths["input_file_path"]
        text = (ROOT / path).read_text()
        for sel in backend["selectors_section"]:
            text = re.sub(sel["regex_selector"], sel["regex_sub"].replace("{{version}}", verstr), text)
        out[path] = text
    return out


def test_stamping_vmn_writes_its_version_into_the_package():
    stamped = _stamp_with("vmn", "1.2.3-rc.4")
    project = toml.loads(stamped["packages/vmn/pyproject.toml"])["project"]
    assert project["version"] == "1.2.3-rc.4"
    version_py = stamped["packages/vmn/src/version_stamp/version.py"]
    assert 'version = "1.2.3-rc.4"' in version_py
    assert '_version = "1.2.3-rc.4"' in version_py
    assert 'name = "vmn"' in version_py


def test_stamping_vmn_exp_writes_one_version_into_both_packages():
    stamped = _stamp_with("vmn_exp", "0.2.0")
    sdk = toml.loads(stamped["packages/vmn-exp-sdk/pyproject.toml"])["project"]
    full = toml.loads(stamped["packages/vmn-exp/pyproject.toml"])["project"]
    assert sdk["version"] == full["version"] == "0.2.0"
    assert "vmn-exp-sdk==0.2.0" in full["dependencies"]
    assert "vmn>0.10.2rc9,<1" in full["dependencies"]  # vmn's own pin is left alone


def test_vmn_stamp_applies_the_release_selectors(app_layout):
    """The selectors above, run through a real `vmn stamp`, not a simulation."""
    import yaml
    from helpers import _init_app, _run_vmn_init, _stamp_app

    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    for dist in ("vmn-exp-sdk", "vmn-exp"):
        source = (ROOT / "packages" / dist / "pyproject.toml").read_text()
        app_layout.write_file_commit_and_push(
            "test_repo_0", f"packages/{dist}/pyproject.toml", source
        )
    app_layout.write_conf(params["app_conf_path"], version_backends=yaml.safe_load(
        (ROOT / ".vmn" / "vmn_exp" / "conf.yml").read_text()
    )["conf"]["version_backends"])

    assert _stamp_app(app_layout.app_name, "minor")[0] == 0

    repo = pathlib.Path(app_layout.repo_path)
    sdk = toml.load(repo / "packages/vmn-exp-sdk/pyproject.toml")["project"]
    full = toml.load(repo / "packages/vmn-exp/pyproject.toml")["project"]
    assert sdk["version"] == full["version"] == "0.1.0"
    assert "vmn-exp-sdk==0.1.0" in full["dependencies"]


def test_vmn_exp_needs_a_vmn_with_the_split():
    """vmn up to 0.10.2rc9 still ships its own `vmn exp` and lacks the plugin
    hooks vmn-exp uses, so `pip install vmn-exp` must never pick it."""
    from packaging.requirements import Requirement

    [vmn] = [Requirement(r) for r in _project("vmn-exp")["dependencies"]
             if Requirement(r).name == "vmn"]
    assert not vmn.specifier.contains("0.10.1")
    assert not vmn.specifier.contains("0.10.2rc9", prereleases=True)
    assert vmn.specifier.contains("0.10.2")
    assert not vmn.specifier.contains("1.0.0")
    # The workspace's own vmn must satisfy it, or editable installs conflict.
    assert vmn.specifier.contains(_project("vmn")["version"], prereleases=True)
