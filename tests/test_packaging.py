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
