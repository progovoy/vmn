"""vmn-exp's ``gitmode.capture`` is a shim over the vmn facade names
(moved from the core suite's test_snapshot_capture_move.py)."""
from version_stamp import api


def test_gitmode_capture_is_the_vmn_capture():
    from vmn_exp.gitmode import capture

    assert capture.Capture is api.SnapshotCapture
    assert capture.capture_snapshot is api.capture_identity
    assert capture.ensure_code is api.ensure_code
