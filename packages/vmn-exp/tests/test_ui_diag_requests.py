"""The requests section: in-flight requests, the slow ones that completed,
and per-route latency since start."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vmn_exp.ui.diag.requests import DiagRequestsMiddleware, RequestTracker


def _app(tracker, release, entered):
    app = FastAPI()

    @app.get("/items/{item}")
    def item(item: str):
        entered.set()
        release.wait(10)
        return {"item": item}

    @app.get("/fast")
    def fast():
        return {}

    app.add_middleware(DiagRequestsMiddleware, tracker=tracker)
    return app


def test_an_in_flight_request_shows_its_route_template_and_age():
    tracker, release, entered = RequestTracker(slow_sec=0.05), threading.Event(), threading.Event()
    with TestClient(_app(tracker, release, entered)) as client:
        t = threading.Thread(target=lambda: client.get("/items/secret-value?q=hidden"),
                             daemon=True)
        t.start()
        try:
            assert entered.wait(5)
            time.sleep(0.1)
            section = tracker.section()
        finally:
            release.set()
            t.join(5)
    flight = section["in_flight"]
    assert len(flight) == 1
    assert flight[0]["method"] == "GET"
    assert flight[0]["route"] == "/items/{item}"
    assert flight[0]["age_sec"] >= 0.05
    assert "hidden" not in str(section) and "secret-value" not in str(section)


def test_a_completed_slow_request_lands_in_the_ring_and_the_route_stats():
    tracker, release, entered = RequestTracker(slow_sec=0.05), threading.Event(), threading.Event()
    with TestClient(_app(tracker, release, entered)) as client:
        threading.Timer(0.15, release.set).start()
        assert client.get("/items/a").status_code == 200
        assert client.get("/fast").status_code == 200
    section = tracker.section()
    assert section["in_flight"] == []
    slow = section["slow"]
    assert [s["route"] for s in slow] == ["/items/{item}"]
    assert slow[0]["status"] == 200 and slow[0]["duration_sec"] >= 0.1
    stats = section["routes"]
    assert stats["GET /items/{item}"]["count"] == 1
    assert stats["GET /fast"]["count"] == 1
    assert {"p50_sec", "p95_sec", "max_sec"} <= set(stats["GET /fast"])


def test_the_slow_ring_is_bounded():
    tracker = RequestTracker(slow_sec=0.0, ring=3)
    for i in range(10):
        tracker.finished(tracker.started({"method": "GET", "path": f"/p{i}"}), 200)
    assert len(tracker.section()["slow"]) == 3


def test_listeners_see_start_and_finish_with_the_request_context():
    from vmn_exp.ui.diag.requests import current_request, note_worker_start

    tracker, seen = RequestTracker(), []
    tracker.add_listener(lambda event, entry: seen.append((event, entry)))
    app = FastAPI()

    @app.get("/work")
    def work():
        note_worker_start()
        current_request().extra["s3_calls"] = 2
        return {}

    app.add_middleware(DiagRequestsMiddleware, tracker=tracker)
    with TestClient(app) as client:
        assert client.get("/work").status_code == 200
    assert [event for event, _ in seen] == ["start", "finish"]
    entry = seen[-1][1]
    assert entry.extra == {"s3_calls": 2}
    assert entry.thread and entry.queue_wait >= 0
    assert entry.route == "/work" and entry.status == 200 and entry.response_bytes > 0


def test_a_raising_listener_never_breaks_a_request():
    tracker = RequestTracker()
    tracker.add_listener(lambda event, entry: 1 / 0)
    entry = tracker.started({"method": "GET", "path": "/x"})
    tracker.finished(entry, 200)
    assert tracker.section()["routes"]["GET /x"]["count"] == 1


def test_api_routes_record_their_queue_wait_and_worker_thread(tmp_path):
    """create_app's role check marks when a route first runs on a pool thread."""
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app = create_app(WorkspaceManager(str(tmp_path / "data")))
    seen = []
    app.state.diag_requests.add_listener(lambda event, entry: seen.append((event, entry)))
    with TestClient(app) as client:
        assert client.get("/api/v1/workspaces").status_code == 200
    entry = [e for event, e in seen if event == "finish"][0]
    assert entry.route == "/api/v1/workspaces"
    assert entry.queue_wait is not None and entry.thread


def test_an_in_flight_request_shows_the_response_bytes_sent_so_far():
    from fastapi.responses import StreamingResponse

    tracker, release, sent = RequestTracker(), threading.Event(), threading.Event()
    app = FastAPI()

    @app.get("/stream")
    def stream():
        def body():
            yield b"x" * 1234
            sent.set()
            release.wait(10)
            yield b"done"
        return StreamingResponse(body())

    app.add_middleware(DiagRequestsMiddleware, tracker=tracker)
    with TestClient(app) as client:
        t = threading.Thread(target=lambda: client.get("/stream"), daemon=True)
        t.start()
        try:
            assert sent.wait(5)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                flight = tracker.section()["in_flight"]
                if flight and flight[0].get("response_bytes"):
                    break
                time.sleep(0.02)
        finally:
            release.set()
            t.join(5)
    assert flight[0]["route"] == "/stream" and flight[0]["response_bytes"] == 1234


def test_requests_show_their_query_parameter_names_never_values():
    tracker, release, entered = RequestTracker(slow_sec=0.05), threading.Event(), threading.Event()
    with TestClient(_app(tracker, release, entered)) as client:
        t = threading.Thread(target=lambda: client.get("/items/a?top=hidden&scope=x&top=y"),
                             daemon=True)
        t.start()
        try:
            assert entered.wait(5)
            time.sleep(0.1)  # past slow_sec: it lands in the slow ring too
            flight = tracker.section()["in_flight"]
        finally:
            release.set()
            t.join(5)
    slow = tracker.section()["slow"]
    assert flight[0]["query_keys"] == ["scope", "top"]
    assert slow[-1]["query_keys"] == ["scope", "top"]
    assert "hidden" not in str(flight) + str(slow)
