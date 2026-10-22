"""The three distributions' declarations (packages/*/pyproject.toml).

See docs/packaging.md. `pip install x[typo]` only warns, and a stale pin only
bites after a release, so these are checked here rather than discovered by users.
"""
import pathlib

import pytest
import toml

ROOT = pathlib.Path(__file__).resolve().parents[3]
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


def test_the_sdk_needs_only_yaml_filelock_and_psutil():
    names = sorted(r.split(">")[0].split("=")[0] for r in _project("vmn-exp-sdk")["dependencies"])
    assert names == ["PyYAML", "filelock", "psutil"]


@pytest.mark.parametrize("dist, extras", [
    ("vmn-exp-sdk", {"s3"}),
    ("vmn-exp", {"ui", "s3", "mlflow"}),
])
def test_documented_extras_exist(dist, extras):
    assert extras <= set(_project(dist).get("optional-dependencies", {}))


@pytest.mark.parametrize("dist", DISTS)
def test_no_distribution_pulls_in_a_training_framework(dist):
    # autolog patches the framework the user already has.
    heavy = [r for r in _requirements(dist) if r.lower().startswith(HEAVY)]
    assert heavy == []


def test_git_cliff_uses_a_range_not_an_exact_pin():
    # Jinja2 templates' {{ release_notes }} need it; an exact pin would fight
    # other packages' constraints.
    [cliff] = [r for r in _project("vmn")["dependencies"] if r.startswith("git-cliff")]
    assert "==" not in cliff and ">=" in cliff and "<" in cliff


def test_gitpython_uses_a_range_not_an_exact_pin():
    # An exact pin fights the resolver when mlflow/dvc constrain GitPython too.
    [git] = [r for r in _project("vmn")["dependencies"] if r.lower().startswith("gitpython")]
    assert "==" not in git and ">=" in git


def test_the_commands_and_the_plugin_are_declared():
    assert set(_project("vmn")["scripts"]) >= {"vmn"}
    assert _project("vmn-exp")["scripts"] == {"vmn-exp": "vmn_exp.cli.main:main"}
    plugins = _project("vmn-exp")["entry-points"]["vmn.plugins"]
    assert plugins == {"dev_version": "vmn_exp.cli.plugin:register_dev_version"}


def test_the_s3_import_error_names_the_extra_to_install():
    from vmn_exp.storage.registry import missing_extra

    s3_base = ROOT / "packages/vmn-exp-sdk/src/vmn_exp/storage/s3_base.py"
    assert 'missing_extra("boto3", "s3")' in s3_base.read_text()
    assert "pip install 'vmn-exp-sdk[s3]'" in str(missing_extra("boto3", "s3"))


def _selector_groups(app):
    import yaml

    conf = yaml.safe_load((ROOT / ".vmn" / app / "conf.yml").read_text())["conf"]
    return conf["version_backends"]["generic_selectors"]


def _template_values(verstr):
    """The ``stamping.app`` fields a selector's ``regex_sub`` renders with."""
    base, _, pre = verstr.partition("-")
    name, _, count = pre.partition(".")
    return {
        "version": verstr,
        "base_version": base,
        "prerelease": name or "release",
        "prerelease_count": {name: int(count)} if name else {},
    }


def _stamp_with(app, verstr):
    """``{path: text}`` after applying *app*'s selectors as `vmn stamp` does."""
    import re

    import jinja2

    values = _template_values(verstr)
    out = {}
    for backend in _selector_groups(app):
        for paths in backend["paths_section"]:
            assert paths["input_file_path"] == paths["output_file_path"]
            path = paths["input_file_path"]
            text = (ROOT / path).read_text()
            for sel in backend["selectors_section"]:
                sub = jinja2.Template(sel["regex_sub"]).render(values)
                text = re.sub(sel["regex_selector"], sub, text)
            out[path] = text
    return out


def _locked_versions(lock_text):
    return {p["name"]: p["version"] for p in toml.loads(lock_text)["package"] if "version" in p}


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


@pytest.mark.parametrize("app, dists", [
    ("vmn", ["vmn"]),
    ("vmn_exp", ["vmn-exp", "vmn-exp-sdk"]),
])
@pytest.mark.parametrize("verstr, locked", [("9.8.7-rc.6", "9.8.7rc6"), ("9.8.7", "9.8.7")])
def test_stamping_an_app_writes_its_version_into_the_workspace_lock(app, dists, verstr, locked):
    # The lock is shared by the workspace; a stamp must leave it current, in
    # the PEP 440 form uv itself writes.
    before = _locked_versions((ROOT / "uv.lock").read_text())
    after = _locked_versions(_stamp_with(app, verstr)["uv.lock"])
    assert {d: after[d] for d in dists} == {d: locked for d in dists}
    assert {k: v for k, v in after.items() if k not in dists} == {
        k: v for k, v in before.items() if k not in dists
    }


def test_vmn_stamp_applies_the_release_selectors(app_layout):
    """The selectors above, run through a real `vmn stamp`, not a simulation."""
    import yaml
    from exp_helpers import _init_app, _run_vmn_init, _stamp_app

    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    for path in ("packages/vmn-exp-sdk/pyproject.toml", "packages/vmn-exp/pyproject.toml", "uv.lock"):
        app_layout.write_file_commit_and_push("test_repo_0", path, (ROOT / path).read_text())
    app_layout.write_conf(params["app_conf_path"], version_backends=yaml.safe_load(
        (ROOT / ".vmn" / "vmn_exp" / "conf.yml").read_text()
    )["conf"]["version_backends"])

    assert _stamp_app(app_layout.app_name, "minor")[0] == 0

    repo = pathlib.Path(app_layout.repo_path)
    sdk = toml.load(repo / "packages/vmn-exp-sdk/pyproject.toml")["project"]
    full = toml.load(repo / "packages/vmn-exp/pyproject.toml")["project"]
    assert sdk["version"] == full["version"] == "0.1.0"
    assert "vmn-exp-sdk==0.1.0" in full["dependencies"]
    locked = _locked_versions((repo / "uv.lock").read_text())
    assert locked["vmn-exp"] == locked["vmn-exp-sdk"] == "0.1.0"

    app_layout.write_file_commit_and_push("test_repo_0", "change.txt", "a change to stamp")
    assert _stamp_app(app_layout.app_name, "patch", prerelease="rc")[0] == 0
    locked = _locked_versions((repo / "uv.lock").read_text())
    assert locked["vmn-exp"] == locked["vmn-exp-sdk"] == "0.1.1rc1"


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
