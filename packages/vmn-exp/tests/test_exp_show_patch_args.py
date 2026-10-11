"""``show --patch`` edges: ``--max-bytes`` must be a positive number (its
help names the default), and an untracked tarball that cannot be read is
reported, never a crash."""
import io
import tarfile

import pytest
from exp_helpers import _exp
from version_stamp.core import logging as vmn_logging
from vmn_exp.cli import views
from vmn_exp.cli.views import UNTRACKED_ONLY, no_patch_note, patch_payload, print_patch

META = {"base_commit": "f" * 40, "code": "k", "has_untracked_files": True}


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _run_cli(capfd, *extra):
    capfd.readouterr()
    try:
        rc = _exp("app", action="show", version="0.0.1", extra_args=list(extra))
    except SystemExit as exc:
        rc = exc.code
    return rc, capfd.readouterr()


@pytest.mark.parametrize("value", ["0", "-5"])
def test_max_bytes_below_one_is_refused(capfd, value):
    rc, out = _run_cli(capfd, "--patch", f"--max-bytes={value}")
    assert rc == 2
    assert "--max-bytes" in out.err and "positive" in out.err


def test_max_bytes_that_is_no_number_is_refused(capfd):
    rc, out = _run_cli(capfd, "--patch", "--max-bytes", "lots")
    assert rc == 2
    assert "--max-bytes" in out.err and "'lots'" in out.err


def test_the_max_bytes_help_names_the_default_cap(capfd, monkeypatch):
    monkeypatch.setattr(views, "PATCH_MAX_BYTES", 4242)
    rc, out = _run_cli(capfd, "--help")
    assert rc == 0
    assert "(default: 4242)" in " ".join(out.out.split())


def _tarball(*names):
    buf = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buf) as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"x\n"))
    return buf.getvalue()


UNREADABLE = [b"\x1f\x8bJUNK", b"not a tarball at all", _tarball("a.py", "b.py")[:30]]
UNREADABLE_IDS = ["corrupt", "not_gzip", "cut_short"]  # the gzip header holds a mtime


@pytest.mark.parametrize("tarball", UNREADABLE, ids=UNREADABLE_IDS)
def test_an_unreadable_untracked_tarball_is_untracked_only_without_names(tarball):
    payload = patch_payload(META, {"untracked_files": tarball})
    assert payload == {"text": None, "reason": UNTRACKED_ONLY}


def test_an_unreadable_deps_tarball_hides_the_names_too():
    patches = {"untracked_files": _tarball("a.py"),
               "deps": {"libs_b": {"untracked_files": UNREADABLE[0]}}}
    assert patch_payload(META, patches) == {"text": None, "reason": UNTRACKED_ONLY}


def test_the_note_of_an_unreadable_tarball_says_so_not_clean_tree():
    note = no_patch_note("v", META, untracked=[])
    assert note.startswith("v has no patch to show: only untracked files were captured")
    assert "cannot be read" in note and "clean tree" not in note


@pytest.mark.parametrize("tarball", UNREADABLE, ids=UNREADABLE_IDS)
def test_show_patch_of_an_unreadable_tarball_prints_a_note(capsys, tarball):
    print_patch("v", META, {"untracked_files": tarball})
    out = capsys.readouterr()
    assert out.out == ""
    assert "only untracked files were captured" in out.err and "cannot be read" in out.err
