import os
import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent
VERSION_STAMP_DIR = ROOT / "version_stamp"


def _get_setup_packages():
    """Parse the packages list from setup.py."""
    setup_path = ROOT / "setup.py"
    ns = {}
    exec(compile(setup_path.read_text(), setup_path, "exec"), ns)
    return ns.get("_setup_packages", None)


def _find_all_subpackages():
    """Find all directories under version_stamp/ that have __init__.py."""
    packages = []
    for dirpath, dirnames, filenames in os.walk(VERSION_STAMP_DIR):
        if "__init__.py" in filenames:
            rel = os.path.relpath(dirpath, ROOT)
            package_name = rel.replace(os.sep, ".")
            packages.append(package_name)
    return sorted(packages)


def _read_setup_packages():
    """Read packages list from setup.py by importing it in isolation."""
    import ast

    setup_path = ROOT / "setup.py"
    tree = ast.parse(setup_path.read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "setup"):
            continue
        for kw in node.keywords:
            if kw.arg == "packages":
                return [elt.value for elt in kw.value.elts]
    return []


def test_all_subpackages_included_in_setup():
    """Every version_stamp subpackage with __init__.py must be in setup.py packages."""
    declared = set(_read_setup_packages())
    on_disk = set(_find_all_subpackages())

    missing = on_disk - declared
    assert not missing, (
        f"Subpackages on disk but missing from setup.py packages list: "
        f"{sorted(missing)}. Add them to the packages= argument in setup.py."
    )


def test_no_stale_packages_in_setup():
    """Every package in setup.py must exist on disk (no stale entries)."""
    declared = set(_read_setup_packages())
    on_disk = set(_find_all_subpackages())

    stale = declared - on_disk
    assert not stale, (
        f"Packages in setup.py that don't exist on disk: "
        f"{sorted(stale)}. Remove them from setup.py."
    )


def _read_setup_extras():
    """Read the extras_require keys from setup.py without importing it."""
    import ast

    tree = ast.parse((ROOT / "setup.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "setup"):
            continue
        for kw in node.keywords:
            if kw.arg == "extras_require":
                return {k.value for k in kw.value.keys}
    return set()


def test_documented_extras_exist():
    """Every extra the docs tell a user to install must actually be declared.

    `pip install vmn[typo]` does not fail — it warns and installs plain vmn — so
    a drifted extra name is a silent no-op for whoever followed the README.
    """
    declared = _read_setup_extras()
    for extra in ("ui", "exp", "s3", "changelog", "sysmetrics"):
        assert extra in declared, f"setup.py is missing the '{extra}' extra"


def test_heavy_frameworks_are_not_pulled_in_by_the_exp_extra():
    """`pip install vmn[exp]` must stay small.

    autolog patches whatever framework the user already has, so vmn never needs
    to install one. Putting torch or tensorflow in `exp` would turn logging three
    numbers into a multi-gigabyte download.
    """
    import ast

    tree = ast.parse((ROOT / "setup.py").read_text())
    extras = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "setup":
            for kw in node.keywords:
                if kw.arg == "extras_require":
                    extras = {
                        k.value: [e.value for e in v.elts]
                        for k, v in zip(kw.value.keys, kw.value.values)
                    }
    heavy = ("torch", "tensorflow", "keras", "lightning")
    for req in extras.get("exp", []):
        assert not req.lower().startswith(heavy), f"'{req}' does not belong in [exp]"


def _read_requirements_txt_lines():
    """Return non-empty, non-comment lines from tests/requirements.txt."""
    req_path = ROOT / "tests" / "requirements.txt"
    return [
        ln.strip()
        for ln in req_path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def test_gitpython_not_exact_pinned():
    """GitPython in install_requires must use a range, not an exact pin.

    An exact ==X.Y.Z fights the resolver when mlflow/dvc declare a different
    constraint.  The CI-exact pin belongs in tests/constraints.txt only.
    """
    lines = _read_requirements_txt_lines()
    gitpython_lines = [ln for ln in lines if ln.lower().startswith("gitpython")]
    assert gitpython_lines, "GitPython not found in tests/requirements.txt"
    for line in gitpython_lines:
        assert "==" not in line, (
            f"GitPython uses an exact pin in tests/requirements.txt: {line!r}. "
            "Use a range like >=3.1.41,<3.2 and put the exact pin in "
            "tests/constraints.txt for CI."
        )
        assert ">=" in line or ">" in line, (
            f"GitPython in tests/requirements.txt has no lower bound: {line!r}"
        )


def test_s3_import_error_suggests_vmn_s3():
    """The boto3 ImportError must direct users to `pip install 'vmn[s3]'`."""
    s3_base = ROOT / "version_stamp" / "cli" / "snapshot_storage_s3_base.py"
    text = s3_base.read_text()
    assert "vmn[s3]" in text, (
        "snapshot_storage_s3_base.py's ImportError should say "
        "`pip install 'vmn[s3]'`, not `pip install boto3`."
    )
