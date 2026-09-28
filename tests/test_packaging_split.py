"""Import rules for the three-distribution split (see docs/packaging.md).

vmn          -> version_stamp
vmn-exp-sdk  -> vmn_exp.{sdk,storage,core,registry,integrations,_base}
vmn-exp      -> vmn_exp.{cli,ui,snapshot,importers,gitmode}
"""
import ast
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SRC = {dist: REPO / "packages" / dist / "src" for dist in ("vmn", "vmn-exp-sdk", "vmn-exp")}
SDK_SUBPACKAGES = ("sdk", "storage", "core", "registry", "integrations", "_base")
FULL_SUBPACKAGES = ("cli", "ui", "snapshot", "importers", "gitmode")
FACADE = "version_stamp.api"
# The SDK may load git mode lazily, from inside a function, and nothing else.
SDK_LAZY_ALLOWED = ("vmn_exp.gitmode",)


def _src_of(path):
    return next(src for src in SRC.values() if src in path.parents)


def _module_name(path):
    parts = path.relative_to(_src_of(path)).with_suffix("").parts
    return ".".join(parts).removesuffix(".__init__")


def _locate(root):
    """*root* (``vmn_exp/sdk``, ``vmn_exp/_base``) in whichever src holds it."""
    for src in SRC.values():
        for candidate in (src / f"{root}.py", src / root):
            if candidate.exists():
                return candidate
    return None


def _imports(path):
    """``[(imported module, is_top_level)]`` for every import in *path*."""
    tree = ast.parse(path.read_text(), filename=str(path))
    top_level = {id(node) for node in tree.body}
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, id(node) in top_level) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                parts = parts[: len(parts) - node.level + 1]
                base = ".".join(parts + ([base] if base else []))
            found.append((base, id(node) in top_level))
    return found


def _files(*roots):
    for root in roots:
        found = _locate(root)
        yield from [found] if found.suffix == ".py" else sorted(found.rglob("*.py"))


def _within(module, package):
    return module == package or module.startswith(package + ".")


def _violations(roots, is_forbidden):
    bad = []
    for path in _files(*roots):
        for module, top_level in _imports(path):
            if is_forbidden(module, top_level):
                bad.append(f"{_module_name(path)} -> {module}")
    return bad


def test_vmn_never_imports_vmn_exp():
    assert _violations(["version_stamp"], lambda m, _: _within(m, "vmn_exp")) == []


@pytest.mark.parametrize("subpackage", SDK_SUBPACKAGES)
def test_sdk_subpackages_stay_off_vmn_and_the_full_platform(subpackage):
    root = f"vmn_exp/{subpackage}"
    if _locate(root) is None:
        pytest.fail(f"{root} does not exist yet")

    def forbidden(module, top_level):
        if _within(module, "version_stamp"):
            return True
        if not top_level and module in SDK_LAZY_ALLOWED:
            return False
        return any(_within(module, f"vmn_exp.{full}") for full in FULL_SUBPACKAGES)

    assert _violations([root], forbidden) == []


def test_full_platform_reaches_vmn_only_through_the_facade():
    roots = [f"vmn_exp/{p}" for p in FULL_SUBPACKAGES if _locate(f"vmn_exp/{p}")]
    assert _violations(
        roots, lambda m, _: _within(m, "version_stamp") and m != FACADE
    ) == []


def test_vmn_exp_is_a_namespace_package():
    assert not [src for src in SRC.values() if (src / "vmn_exp" / "__init__.py").exists()]


def test_every_vmn_exp_subpackage_belongs_to_one_distribution():
    def names(dist):
        return {p.stem for p in (SRC[dist] / "vmn_exp").iterdir() if p.name != "__pycache__"}

    assert names("vmn-exp-sdk") == set(SDK_SUBPACKAGES)
    assert names("vmn-exp") == set(FULL_SUBPACKAGES)
    assert not (SRC["vmn"] / "vmn_exp").exists()


def test_vmn_names_no_plugin_module():
    # Plugins arrive through the ``vmn.plugins`` entry point group; a module name
    # in a string would be an import edge the AST scan above cannot see.
    source = (SRC["vmn"] / "version_stamp" / "cli" / "plugins.py").read_text()
    assert "vmn_exp" not in source
