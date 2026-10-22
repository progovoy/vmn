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
