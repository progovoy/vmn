"""version_stamp.snapshot.identity: the leaf module of snapshot naming/identity."""
import subprocess
import sys

import pytest

from version_stamp.snapshot import identity

MOVED = (
    "safe_dep_name",
    "safe_verstr",
    "unsafe_verstr",
    "same_state",
    "_compute_diff_hash",
    "_format_dev_verstr",
    "_unique_snapshot_verstr",
    "_DIFF_HASH_LENGTHS",
)


def test_identity_is_a_leaf_module():
    code = (
        "import sys, version_stamp.snapshot.identity; "
        "print(sorted(m for m in sys.modules if m.startswith("
        "('version_stamp.devversion', 'version_stamp.snapshot.record', "
        "'version_stamp.cli'))))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]"


@pytest.mark.parametrize("name", MOVED)
def test_old_locations_re_export_the_identity_objects(name):
    from version_stamp.devversion import capture
    from version_stamp.snapshot import record

    moved = getattr(identity, name)
    for module in (capture, record):
        if hasattr(module, name):
            assert getattr(module, name) is moved


def test_api_names_resolve_to_identity_objects():
    from version_stamp import api

    for name in ("_compute_diff_hash", "_format_dev_verstr", "_unique_snapshot_verstr"):
        assert getattr(api, name) is getattr(identity, name)


def test_identity_helpers_behave():
    assert identity.safe_verstr("1.0.0+b") == "1.0.0_plus_b"
    assert identity.unsafe_verstr("1.0.0_plus_b") == "1.0.0+b"
    assert identity.safe_dep_name("../libs/a") == ".._libs_a"
    with pytest.raises(ValueError):
        identity.safe_verstr("../x")
    assert identity._format_dev_verstr("1.0.0", "abcdef0123", None) == (
        "1.0.0-dev.abcdef0.0000000"
    )
    assert identity._compute_diff_hash({}) is None
