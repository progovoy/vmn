"""Store reads fanned out to thread pools run in the caller's contextvars
context, so the ``vmn-exp ui`` dump attributes their S3 calls to the request
that issued them (a ``ThreadPoolExecutor`` worker does not inherit it)."""
import contextvars

from vmn_exp.core.subtree_direct import subtree_rows_direct
from vmn_exp.storage.s3_base import parallel_map
from vmn_exp.storage.thread_context import in_caller_context

WHO = contextvars.ContextVar("who", default=None)


def test_in_caller_context_runs_fn_with_the_wrapping_threads_values():
    from concurrent.futures import ThreadPoolExecutor

    WHO.set("request-1")
    read = in_caller_context(lambda item: (item, WHO.get()))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(read, range(8))) == [(i, "request-1") for i in range(8)]


def test_parallel_map_carries_the_callers_context():
    WHO.set("request-2")
    assert parallel_map(lambda item: WHO.get(), range(6)) == ["request-2"] * 6


class _Storage:
    """A flat outer run ``root`` with two children, every read noting WHO."""

    def __init__(self):
        self.seen = set()
        self.metas = {"root": {"verstr": "root", "timestamp": "1"},
                      "a": {"verstr": "a", "parent": "root", "timestamp": "2"},
                      "b": {"verstr": "b", "parent": "root", "timestamp": "3"}}

    def load_metadata(self, app, verstr):
        self.seen.add(WHO.get())
        return self.metas.get(verstr)

    def load_file(self, app, verstr, name):
        self.seen.add(WHO.get())
        return None

    def list_children(self, app, verstr):
        self.seen.add(WHO.get())
        return ["a", "b"] if verstr == "root" else []


def test_subtree_rows_direct_reads_in_the_callers_context():
    WHO.set("request-3")
    storage = _Storage()
    subtree = subtree_rows_direct(storage, "my_app", "root")
    assert [r["verstr"] for r in subtree.rows] == ["root", "a", "b"]
    assert storage.seen == {"request-3"}


class _Ranges:
    def read_range(self, app, verstr, name, start, end):
        return WHO.get()


def test_series_segment_reads_carry_the_callers_context():
    from vmn_exp.core.series_reader import _read_all

    WHO.set("request-4")
    objects = [(f"metrics/w~{i}.vms", 10) for i in range(5)]
    assert _read_all(_Ranges(), "my_app", "v", objects) == ["request-4"] * 5


def test_run_detail_reads_carry_the_callers_context():
    from vmn_exp.ui.readers.detail_reads import submit

    WHO.set("request-5")
    assert submit(WHO.get).result(10) == "request-5"


def test_batched_series_reads_carry_the_callers_context(monkeypatch):
    from vmn_exp.ui import routes_series

    monkeypatch.setattr(routes_series.detail_reader, "run_series",
                        lambda *a, **k: ({"who": WHO.get()}, {}, {}))
    WHO.set("request-6")
    payload = routes_series.batch_series(None, "my_app", ["a", "b", "c"], None, 10)
    assert [s["who"] for s in payload["series"].values()] == ["request-6"] * 3
