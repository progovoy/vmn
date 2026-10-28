"""``vmn-exp ui diag --summarize`` reads the newer sections too: held locks
and their waiters, long-running background work, S3 calls by object kind
and by who made them, recent errors, event-loop/GIL lag."""
from vmn_exp.ui.diag_summary import summarize


def _dump(**sections):
    return {"format": 1, "taken_at": "t", "pid": 1, "sections": sections}


def test_a_lock_held_for_minutes_names_its_holder_and_waiters():
    locks = {"held": [{"name": "report index:prod", "holder": "vmn-ui-reports",
                       "held_sec": 301.2,
                       "waiters": [{"thread": "AnyIO worker thread", "waiting_sec": 288.0},
                                   {"thread": "vmn-ui-refresh", "waiting_sec": 12.4}]}],
             "stats": []}
    text = summarize(_dump(locks=locks))
    assert "report index:prod held 301.2s by vmn-ui-reports" in text
    assert "2 waiting, longest 288.0s" in text


def test_background_work_running_long_and_its_last_errors():
    background = {"activities": [
        {"name": "report index refresh", "key": "prod", "runs": 4,
         "running": [{"thread": "vmn-ui-reports", "running_sec": 301.2}],
         "last_error": {"error": "ClientError('SlowDown')", "ago_sec": 30.0}},
        {"name": "board warm", "key": "app", "runs": 9, "running": [], "last_sec": 0.2}]}
    text = summarize(_dump(background=background))
    assert "report index refresh [prod]: running 301.2s" in text
    assert "ClientError('SlowDown')" in text
    assert "board warm" not in text  # idle and healthy: noise


def test_s3_by_kind_failures_and_callers():
    s3 = {"operations": {}, "by_kind": {
        "GetObject run_state.yml": {"count": 61000, "errors": {"NoSuchKey": 24800},
                                    "latency_ms": {"p50": 20, "p95": 50, "max": 400}},
        "ListObjectsV2 journal": {"count": 54000, "errors": {},
                                  "latency_ms": {"p50": 30, "p95": 900, "max": 31000}}},
        "recent_other_failures": [{"operation": "GetObject", "key": "a/b/metadata.yml",
                                   "error": "AccessDenied", "status": 403, "age_sec": 2}],
        "by_thread": {"vmn-ui-reports": {"ListObjectsV2": {"n": 54000, "ms": 9e6, "err": 0}},
                      "vmn-ui-refresh": {"GetObject": {"n": 3, "ms": 30, "err": 0}}}}
    text = summarize(_dump(s3=s3))
    assert text.index("GetObject run_state.yml") < text.index("ListObjectsV2 journal")
    assert "NoSuchKey=24800" in text
    assert "AccessDenied" in text and "a/b/metadata.yml" in text
    assert text.index("vmn-ui-reports") < text.index("vmn-ui-refresh")


def test_in_flight_requests_show_their_s3_calls():
    requests = {"in_flight": [{"method": "GET", "route": "/x", "age_sec": 300,
                               "query_keys": ["scope", "top"],
                               "s3": {"ListObjectsV2": {"n": 900, "ms": 280000, "err": 0}}}]}
    text = summarize(_dump(requests=requests))
    assert "/x ?scope,top" in text and "ListObjectsV2 900" in text


def test_recent_errors_and_lag():
    logs = {"recent": [{"level": "ERROR", "logger": "vmn_exp.ui.refresher",
                        "message": "refresh failed", "exc_type": "ZeroDivisionError"}],
            "counts": [{"logger": "vmn_exp.ui.refresher", "level": "ERROR", "count": 7}]}
    latency = {"event_loop": {"p50_ms": 0.4, "p95_ms": 2.1, "max_ms": 4100.0},
               "thread": {"p50_ms": 4.5, "p95_ms": 900.0, "max_ms": 2500.0}}
    text = summarize(_dump(logs=logs, latency=latency))
    assert "7 ERROR vmn_exp.ui.refresher" in text
    assert "refresh failed (ZeroDivisionError)" in text
    assert "event loop lag p95 2.1ms max 4100.0ms" in text and "STALLED" in text


def test_s3_prefixes_that_waited_for_a_slot():
    s3 = {"operations": {}, "prefix_caps": {"limit": 64, "prefixes_seen": 3, "prefixes": [
        {"bucket": "b", "prefix": "vmn/runs/app", "limit": 64, "in_flight": 64,
         "peak_in_flight": 64, "waiting": 120, "waits": 9000,
         "wait_ms_total": 81000.0, "wait_ms_max": 2500.0},
        {"bucket": "b", "prefix": "vmn/journal", "limit": 64, "in_flight": 1,
         "peak_in_flight": 3, "waiting": 0, "waits": 0,
         "wait_ms_total": 0.0, "wait_ms_max": 0.0}]}}
    text = summarize(_dump(s3=s3))
    assert "S3 prefix caps (64 calls in flight a prefix):" in text
    assert "b/vmn/runs/app: 64 in flight, 120 waiting; 9000 waits, max 2.5s" in text
    assert "vmn/journal" not in text  # never waited: noise


def test_odd_shapes_never_break_the_summary():
    text = summarize(_dump(locks=[1], background="x", logs={"recent": 3}, latency=None,
                           s3={"operations": {}, "by_kind": [1]}))
    assert text.startswith("vmn-exp ui diag")
