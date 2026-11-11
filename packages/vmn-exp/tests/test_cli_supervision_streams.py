"""`vmn-exp run` compacts every stream it appended to (plan 38 A5): when the
child's run compacts its own stream on a shared copy, the copy moves to a new
owner and the supervisor's later appends land in a stream of the new owner."""
import argparse
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from stream_fakes import APP, V, StreamRecorder

from vmn_exp.cli import run as runmod
from vmn_exp.cli import supervisor
from vmn_exp.cli.run import _Supervision
from vmn_exp.core.writer import set_default_writer_id


@pytest.fixture(autouse=True)
def host(monkeypatch):
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    set_default_writer_id("host")
    logger = MagicMock()
    monkeypatch.setattr(supervisor, "VMN_LOGGER", logger)
    monkeypatch.setattr(runmod, "VMN_LOGGER", logger)


@pytest.fixture
def compacted(monkeypatch):
    streams = []
    monkeypatch.setattr(runmod, "compact_by",
                        lambda storage, app, verstr, stream, deadline: streams.append(stream))
    return streams


class _NoMetrics:
    def poll(self):
        return []


def _supervision(storage):
    args = argparse.Namespace(capture_output=False, kill_grace_sec=1)
    sup = _Supervision(storage, APP, V, args, wait=threading.Event().wait)
    sup.start, sup.tailer = 0.0, _NoMetrics()
    return sup


def _ingest_across_an_owner_change(copy, sup):
    sup._ingest([(1, {"loss": 1.0})])
    copy.owner = "o2"
    sup._ingest([(2, {"loss": 0.5})])


def test_supervision_notes_each_stream_it_appends_to_across_an_owner_change():
    copy = StreamRecorder()
    sup = _supervision(copy)

    _ingest_across_an_owner_change(copy, sup)
    sup._ingest([])

    assert sup.appended_streams == {"host~o1", "host~o2"}
    assert copy.metric_blocks == ["host~o1", "host~o2"]


def test_finish_compacts_the_noted_streams_and_the_current_one(compacted):
    copy = StreamRecorder()
    sup = _supervision(copy)
    _ingest_across_an_owner_change(copy, sup)
    copy.owner = "o3"

    sup._finish(SimpleNamespace(returncode=0), ["train"])

    assert sorted(compacted) == ["host~o1", "host~o2", "host~o3"]
