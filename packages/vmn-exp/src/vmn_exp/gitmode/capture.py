#!/usr/bin/env python3
"""Snapshot capture for a new run: outside the repo lock, once per code identity.

The capture itself lives in vmn (``version_stamp.snapshot.capture``, see its
docstring), shared with ``vmn snapshot``. These module attributes are what
experiment code calls (``capture.capture_snapshot(...)``), so tests can
monkeypatch them here.
"""
from version_stamp.api import SnapshotCapture as Capture  # noqa: F401
from version_stamp.api import capture_identity as capture_snapshot  # noqa: F401
from version_stamp.api import ensure_code as _core_ensure_code
from vmn_exp.snapshot.core_code import CoreCodeStore


def ensure_code(storage, vcs, captured):
    """vmn's ``ensure_code`` over *storage*'s ``code`` area."""
    return _core_ensure_code(CoreCodeStore(storage), vcs, captured)
