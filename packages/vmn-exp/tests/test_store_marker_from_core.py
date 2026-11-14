"""The SDK's store.yml marker is core's (plan 37 P5d): vmn_exp.storage.store_marker
re-exports version_stamp.store.marker and only wires the real time functions."""
import pytest
import yaml

from version_stamp.store import marker as core
from version_stamp.store import marker_roots as core_roots
from vmn_exp.storage import store_marker as sdk

SHARED = ("MARKER", "LAYOUT", "LocalRoot", "ObjectRoot", "root_of", "require_store",
          "authoritative", "forget_checked", "StoreLayoutError", "MissingStoreError",
          "_lock")


@pytest.mark.parametrize("name", SHARED)
def test_the_sdk_name_is_cores_object(name):
    assert getattr(sdk, name) is getattr(core, name)


def test_the_roots_are_the_marker_roots_module():
    assert sdk.LocalRoot is core_roots.LocalRoot
    assert sdk.ObjectRoot is core_roots.ObjectRoot


class _Backend:
    """A local backend as root_of sees it (``root`` and ``area``)."""

    def __init__(self, root):
        self.root, self.area = root, "runs"


def test_check_store_keeps_its_old_signature(tmp_path):
    root = tmp_path / "store"
    sdk.forget_checked()
    try:
        sdk.check_store(_Backend(str(root)), writer=True)
        sdk.check_store(_Backend(str(root)), True)
    finally:
        sdk.forget_checked()
    marker = yaml.safe_load((root / "store.yml").read_text())
    assert marker["layout"] == 2 and marker["journal"] == {"partition": "minute"}


def test_check_store_errors_are_cores(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    (root / "store.yml").write_text("layout: 3\n")
    sdk.forget_checked()
    try:
        with pytest.raises(core.StoreLayoutError, match="has store layout 3"):
            sdk.check_store(_Backend(str(root)), writer=False)
    finally:
        sdk.forget_checked()


def test_new_marker_keeps_its_old_signature():
    marker = sdk.new_marker()
    assert marker["layout"] == 2
    assert marker["created_at"].endswith("Z")
