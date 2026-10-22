"""The human summary of a ``vmn-exp ui`` diagnostic dump (``vmn-exp ui diag``):
tolerant of missing, empty or differently shaped sections."""
from vmn_exp.ui.diag_summary import summarize

SLOW_STACK = ["server.py:10 in handle", "index.py:99 in load", "s3_records.py:40 in read"]


def _dump(**sections):
    return {"format": 1, "taken_at": "2026-10-22T10:00:00Z", "pid": 4242,
            "sections": sections}


def test_header_names_the_process_and_the_time():
    text = summarize(_dump())
    assert "4242" in text and "2026-10-22T10:00:00Z" in text


def test_groups_identical_thread_stacks_by_count():
    threads = [{"name": f"w{i}", "stack": SLOW_STACK} for i in range(7)]
    threads.append({"name": "main", "stack": ["main.py:1 in run"]})
    text = summarize(_dump(threads=threads))
    assert "7 threads" in text
    assert "s3_records.py:40 in read" in text
    assert text.index("s3_records.py") < text.index("main.py:1")


def test_takes_pre_grouped_stacks():
    text = summarize(_dump(stacks=[{"count": 12, "stack": "\n".join(SLOW_STACK)}]))
    assert "12 threads" in text and "index.py:99 in load" in text


def test_lists_the_slowest_in_flight_requests_first():
    requests = {"in_flight": [
        {"method": "GET", "path": "/api/v1/fast", "age_ms": 5},
        {"method": "GET", "path": "/api/v1/slow", "age_ms": 90_000},
    ]}
    text = summarize(_dump(requests=requests))
    assert text.index("/api/v1/slow") < text.index("/api/v1/fast")
    assert "90.0s" in text


def test_flags_a_saturated_pool():
    pools = {"store-readers": {"max_workers": 32, "active": 32, "queued": 900},
             "idle": {"max_workers": 8, "active": 1, "queued": 0}}
    text = summarize(_dump(pools=pools))
    line = next(ln for ln in text.splitlines() if "store-readers" in ln)
    assert "32/32" in line and "900" in line and "SATURATED" in line
    assert "SATURATED" not in next(ln for ln in text.splitlines() if "idle" in ln)


def test_reports_index_loading_wherever_it_sits():
    index = {"apps": {"ws/my_app": {"loading": [12000, 45386]},
                      "ws/done": {"loading": None}}}
    text = summarize(_dump(index=index))
    assert "ws/my_app" in text and "12000/45386" in text
    assert "ws/done" not in text


def test_shows_s3_p95_per_operation_and_errors():
    s3 = {"operations": {
        "GetObject": {"count": 500, "errors": {"NoSuchKey": 3}, "retries": 2, "in_flight": 60,
                      "latency_ms": {"p50": 20, "p95": 2000, "max": 9000}},
        "ListObjectsV2": {"count": 10, "errors": {}, "retries": 0, "in_flight": 0,
                          "latency_ms": {"p50": 50, "p95": 100, "max": 120}}},
        "max_pool_connections": [64], "clients_created": 3,
        "clients": [{"client": 1, "max_pool_connections": 64, "in_flight": 64}],
        "in_flight": [{"operation": "GetObject", "path": "/runs/a/metadata.yml", "age_ms": 30000}]}
    text = summarize(_dump(s3=s3))
    get = next(ln for ln in text.splitlines() if ln.strip().startswith("GetObject"))
    assert "500" in get and "2000" in get and "NoSuchKey=3" in get
    assert text.index("GetObject") < text.index("ListObjectsV2")  # slowest p95 first
    assert "64/64" in text
    assert "/runs/a/metadata.yml" in text


def test_tolerates_missing_broken_and_odd_sections():
    text = summarize(_dump(threads="oops", requests=None, pools=[1, 2], s3={"operations": 5},
                           index={"error": "boom"}, custom={"x": 1}))
    assert "boom" in text
    assert summarize({}) and summarize({"sections": None})


REAL_DUMP = {
    "format": 1, "pid": 7, "taken_at": "2026-10-22T05:00:00Z",
    "sections": {
        "threads": {"count": 41, "groups": [
            {"count": 32, "threads": [], "stack": ['  File "index.py", line 9, in _load_chunk\n']},
            {"count": 1, "threads": [], "stack": ['  File "server.py", line 3, in serve\n']},
        ]},
        "requests": {"in_flight": [
            {"method": "POST", "route": "/api/v1/workspaces/{ws}/apps/{app}/series",
             "age_sec": 125.5, "queue_wait_sec": 120.0, "thread": "AnyIO worker"},
            {"method": "GET", "route": "/api/v1/meta", "age_sec": 0.2, "queue_wait_sec": None},
        ], "slow": [], "routes": {}},
        "pools": {"default": {"borrowed": 40, "total": 40, "waiting": 17},
                  "slow_read": {"borrowed": 3, "total": 24, "waiting": 0}},
        "indexes": {"background": True, "watched": [
            {"app": "fastglobalmacro", "rows": 12500, "loading": {"loaded": 12500, "total": 46000},
             "refreshing": True, "last_refresh_sec": 4.2}]},
    },
}


def test_summary_reads_the_dump_sections_as_vmn_exp_ui_writes_them():
    text = summarize(REAL_DUMP)
    assert "32 threads" in text and "_load_chunk" in text
    assert "125.5s" in text and "series" in text and "queued 120.0s" in text
    assert "default: 40/40 busy, 17 waiting  SATURATED" in text
    assert "slow_read: 3/24 busy, 0 waiting" in text
    assert "fastglobalmacro: 12500/46000 loaded" in text


def test_stack_groups_name_their_threads_and_skip_stdlib_wait_frames():
    stack = ['  File "/srv/vmn_exp/reports/index.py", line 90, in refresh\n    self._catch_up()',
             '  File "/srv/vmn_exp/core/journal_reader.py", line 81, in tick\n    keys = x()',
             '  File "/usr/lib/python3.10/threading.py", line 320, in wait\n    waiter.acquire()',
             '  File "/usr/lib/python3.10/queue.py", line 171, in get\n    self.not_empty.wait()']
    threads = {"count": 2, "groups": [{"count": 2, "stack": stack, "threads": [
        {"name": "vmn-ui-reports"}, {"name": "AnyIO worker thread"}]}]}
    text = summarize(_dump(threads=threads))
    assert "2 threads (vmn-ui-reports, AnyIO worker thread)" in text
    assert "journal_reader.py" in text and "reports/index.py" in text
    assert "queue.py" not in text
