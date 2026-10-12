"""Helpers for the multi-clone tests: several local roots on one host (clones,
worktrees, islands) record under one writer id into one run over one S3 store.
Each root appends to its own stream (``<writer>~<owner>``, own_stream), as
every vmn command does."""
from contextlib import contextmanager

from s3_helpers import mocked_bucket, s3_storage
from vmn_exp.core import writer as experiment_writer
from vmn_exp.core.metric_block import encode_block
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.core.writer import own_stream

APP = "app"
V = "0.0.1-dev.aaa1111.bbb2222"
W = "h"

LOG_CALLS = ("log_objects", "log_object_groups", "load_file", "save_file",
             "create_log_segment", "put_log_segment")
METRIC_CALLS = ("metric_objects", "read_range", "create_metric_segment",
                "put_metric_segment", "put_indexed", "drop_indexed")
_WRITES = {"save_file", "create_log_segment", "put_log_segment",
           "create_metric_segment", "put_metric_segment", "put_indexed",
           "drop_indexed"}


@contextmanager
def one_host_bucket(monkeypatch):
    """A mocked S3 bucket, every command of this host recording as writer W."""
    from vmn_exp.storage import buffered

    with mocked_bucket(monkeypatch):
        monkeypatch.setenv("VMN_WRITER_ID", W)
        experiment_writer._WRITER_ID = None
        yield
        buffered.close_all()


def stream(host):
    """The stream *host* appends to in run V: the one a command over it would."""
    return own_stream(host, APP, V)


def flaky(host, rng, p, names, lost_responses=True):
    """Each of *host*'s remote calls among *names* fails with probability *p*;
    with *lost_responses*, a failing write half the time takes effect first
    (the upload landed, its response was lost)."""
    for name in names:
        real = getattr(host._remote, name, None)
        if real is None:
            continue

        def call(*args, _real=real, _name=name, **kw):
            if rng.random() >= p:
                return _real(*args, **kw)
            if lost_responses and _name in _WRITES and rng.random() < 0.5:
                _real(*args, **kw)
            raise RuntimeError("network blip")

        setattr(host._remote, name, call)


def lose_next_response(host, names):
    """*host*'s next remote write among *names* lands, then raises."""
    lost = []
    for name in names:
        real = getattr(host._remote, name, None)
        if real is None or name not in _WRITES:
            continue

        def call(*args, _real=real, **kw):
            result = _real(*args, **kw)
            if not lost:
                lost.append(True)
                raise RuntimeError("response lost")
            return result

        setattr(host._remote, name, call)


def quietly(call, *args):
    """*call(*args)*, or False when it raises (a command on a flaky network)."""
    try:
        return call(*args)
    except Exception:
        return False


def tag(step, key, text="v"):
    return {"timestamp": f"2026-01-01T00:{step // 60:02d}:{step % 60:02d}Z",
            "type": "tags", "set": {key: text}}


def tag_keys(entries):
    return sorted(k for e in entries if e.get("type") == "tags" for k in e["set"])


def remote_tag_keys():
    """The tag keys of every stream of writer W the remote holds."""
    logs = s3_storage().load_logs_by_writer(APP, V)
    return tag_keys(e for s, entries in logs.items() if s.split("~")[0] == W
                    for e in entries)


def view_tag_keys(storage):
    return tag_keys(storage.load_merged_log(APP, V))


def block(*values, start=0):
    """One metric block of key ``x``: *values* at steps (and microsecond
    timestamps) *start* + 1, *start* + 2, ... — never a whole second, whose
    ISO form sorts after the fractional ones of the same second."""
    at = list(range(start + 1, start + 1 + len(values)))
    return encode_block({"x": Columns(at, at, list(values))})


def metric_values(storage):
    """Every point of key ``x`` *storage* reads, sorted."""
    reader = SeriesReader.from_storage(storage, APP, V, rewinds=())
    return sorted(reader.points("x").values)


def remote_metric_values():
    return metric_values(s3_storage())


def fail_once(host, op, key_part):
    """*host*'s next S3 *op* on a key containing *key_part* fails; the list
    it returns is non-empty once it did."""
    client = host._remote._s3
    real, hit = getattr(client, op), []

    def call(*args, **kw):
        if not hit and key_part in str(kw.get("Key", kw.get("Prefix", ""))):
            hit.append(True)
            raise RuntimeError(f"blip {op}")
        return real(*args, **kw)

    setattr(client, op, call)
    return hit
