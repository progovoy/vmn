from types import SimpleNamespace

from version_stamp.cli.output import goto_version
from version_stamp.core.logging import init_stamp_logger


init_stamp_logger()


class RecordingBackend:
    def __init__(self, tag_hash):
        self.tag_hash = tag_hash
        self.checkouts = []

    def changeset(self, tag=None):
        assert tag == "app_1.2.3"
        return self.tag_hash

    def checkout(self, tag=None):
        self.checkouts.append(tag)


def _legacy_vcs(tag_hash="abcdef1234567890"):
    backend = RecordingBackend(tag_hash)
    app_data = {"_version": "1.2.3"}
    ver_infos = {
        "app_1.2.3": {
            "ver_info": {"stamping": {"app": app_data}},
        }
    }
    vcs = SimpleNamespace(
        backend=backend,
        configured_deps={".": {}},
        get_version_info_from_verstr=lambda version: ("app_1.2.3", ver_infos),
        name="app",
        root_context=False,
        vmn_root_path="/unused",
    )
    return vcs, backend


def test_goto_legacy_tag_without_changesets_succeeds():
    vcs, backend = _legacy_vcs()

    assert goto_version(vcs, {"deps_only": False}, "1.2.3", False) == 0
    assert backend.checkouts == ["app_1.2.3"]


def test_goto_legacy_unique_id_is_validated_before_checkout():
    vcs, backend = _legacy_vcs()

    assert goto_version(vcs, {"deps_only": False}, "1.2.3+wrong", False) == 1
    assert backend.checkouts == []


def test_goto_legacy_unique_id_uses_tag_commit():
    vcs, backend = _legacy_vcs("abcdef1234567890")

    assert goto_version(vcs, {"deps_only": False}, "1.2.3+abcdef", False) == 0
    assert backend.checkouts == ["app_1.2.3"]
