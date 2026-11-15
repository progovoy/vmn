"""Plan 39 B4a: plain ``vmn-exp show`` says a run captured untracked files,
from its metadata or the tarball itself, without listing the tarball."""
import argparse
import io
import tarfile

from vmn_exp.cli.experiment import experiment_show
from vmn_exp.core.real_io import RealConsole
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import RealClock

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.0000001"


def _tarball(*names):
    buf = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buf) as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = 2
            tar.addfile(info, io.BytesIO(b"x\n"))
    return buf.getvalue()


def _show(tmp_path, capsys, metadata, patches):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    meta = dict({"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, **metadata)
    storage.save(APP, VERSTR, meta, patches)
    args = argparse.Namespace(name=APP, version=[VERSTR], json=False)
    assert experiment_show(None, None, storage, args, RealConsole(), clock=RealClock()) == 0
    return capsys.readouterr().out


def test_show_says_untracked_files_were_captured(tmp_path, capsys):
    out = _show(tmp_path, capsys, {"has_untracked_files": True}, {})
    assert "  untracked_files: captured" in out.splitlines()


def test_show_says_so_from_the_tarball_alone_without_listing_it(tmp_path, capsys):
    out = _show(tmp_path, capsys, {}, {"untracked_files": _tarball("train2.py")})
    assert "  untracked_files: captured" in out.splitlines()
    assert "train2.py" not in out


def test_show_of_a_run_without_untracked_files_says_nothing_of_them(tmp_path, capsys):
    out = _show(tmp_path, capsys, {}, {"working_tree": "diff --git a/f b/f\n"})
    assert "untracked" not in out
