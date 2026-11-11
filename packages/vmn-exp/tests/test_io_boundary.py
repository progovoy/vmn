"""Ratchet: no new direct IO in vmn-exp (CLAUDE.md "IO behind interfaces").

Every module of the two vmn_exp src roots is scanned with io_scan.scan and
compared with io_boundary_known.KNOWN_IO. A count may only go down, and an
entry must be lowered in the same commit that removes a call. Regenerate:
    python packages/vmn-exp/tests/test_io_boundary.py --regen
"""
import ast
import sys
from pathlib import Path

from io_boundary_known import KNOWN_IO, REAL_IO, REAL_WIRED
from io_scan import scan

REPO = Path(__file__).resolve().parents[3]
SRC_ROOTS = [REPO / "packages" / dist / "src" for dist in ("vmn-exp-sdk", "vmn-exp")]
REGEN = "python packages/vmn-exp/tests/test_io_boundary.py --regen"


def _module_name(path, src):
    return ".".join(path.relative_to(src).with_suffix("").parts).removesuffix(".__init__")


def _module_paths():
    return {
        _module_name(path, src): path
        for src in SRC_ROOTS
        for path in sorted((src / "vmn_exp").rglob("*.py"))
    }


def _actual_io():
    found = {}
    for module, path in _module_paths().items():
        counts = scan(path.read_text())
        if counts:
            found[module] = dict(sorted(counts.items()))
    return found


def _top_level_names(path):
    names = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return names


def test_no_module_exceeds_its_known_io():
    over = [
        f"{module}: {kind} {count} > {KNOWN_IO.get(module, {}).get(kind, 0)}"
        for module, counts in _actual_io().items()
        for kind, count in counts.items()
        if count > KNOWN_IO.get(module, {}).get(kind, 0)
    ]
    assert not over, (
        "New direct IO; take it as an injected parameter instead "
        f"(or, for a real implementation, run `{REGEN}`):\n  " + "\n  ".join(over)
    )


def test_known_io_has_no_stale_entries():
    actual = _actual_io()
    stale = [
        f"{module}: {kind} known {known} > actual {actual.get(module, {}).get(kind, 0)}"
        for module, counts in KNOWN_IO.items()
        for kind, known in counts.items()
        if known > actual.get(module, {}).get(kind, 0)
    ]
    assert not stale, f"Direct IO went down; lower the list with `{REGEN}`:\n  " + "\n  ".join(stale)


def test_real_io_entries_name_existing_modules_and_carry_a_reason():
    modules = _module_paths()
    bad = [m for m, reason in REAL_IO.items() if m not in modules or not reason.strip()]
    assert not bad


def test_real_wired_entries_name_existing_names_and_carry_a_reason():
    modules = _module_paths()
    bad = [
        name
        for name, (module, reason) in REAL_WIRED.items()
        if module not in modules
        or name not in _top_level_names(modules[module])
        or not reason.strip()
    ]
    assert not bad


def _regen():
    lines = [
        f"# AUTO-GENERATED (KNOWN_IO) by: {REGEN}",
        "# KNOWN_IO only shrinks. REAL_IO and REAL_WIRED are hand-kept and survive --regen.",
        "",
        f"REAL_IO = {REAL_IO!r}",
        f"REAL_WIRED = {REAL_WIRED!r}",
        "",
        "KNOWN_IO = {",
    ]
    lines += [f"    {module!r}: {counts!r}," for module, counts in sorted(_actual_io().items())]
    lines += ["}", ""]
    out = Path(__file__).parent / "io_boundary_known.py"
    out.write_text("\n".join(lines))
    print(f"Written: {out}")


if __name__ == "__main__":
    if "--regen" not in sys.argv:
        sys.exit(f"Usage: {REGEN}")
    _regen()
