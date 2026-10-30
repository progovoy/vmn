"""``vmn-exp ui diag --summarize`` reads the ``gc`` section: collections and
their worst pause, how the collector is set up, the allocator next to RSS
(retained memory shows as many bytes per allocated block), and whether the
event loop's worst stall was a GC pause."""
from vmn_exp.ui.diag_summary import summarize

AT = 1_700_000_000.0


def _dump(**sections):
    return {"format": 1, "taken_at": "t", "pid": 1, "sections": sections}


def _gc(**over):
    section = {
        "enabled": True, "gil_enabled": False, "threshold": [2000, 10, 10],
        "freeze_count": 8_000_000, "collections": 3, "total_ms": 115_000.0,
        "max_ms": 114_000.0, "max_at": AT, "max_generation": 2,
        "collected": 120, "uncollectable": 0,
        "recent": [{"at": AT - 600, "ms": 900.0, "generation": 0, "collected": 20,
                    "uncollectable": 0},
                   {"at": AT, "ms": 114_000.0, "generation": 2, "collected": 100,
                    "uncollectable": 0}],
        "allocator": {"name": "mimalloc", "allocated_blocks": 36_000_000,
                      "env": {"MIMALLOC_PURGE_DELAY": "0"}},
    }
    section.update(over)
    return section


def test_collections_and_their_worst_pause():
    text = summarize(_dump(gc=_gc()))
    assert "3 collections, 115.0s paused, max 114.0s (gen 2" in text
    assert "120 collected, 0 uncollectable" in text


def test_the_collector_setup_and_the_allocator():
    text = summarize(_dump(gc=_gc()))
    assert "free-threaded" in text and "8.0M frozen" in text
    assert "mimalloc" in text and "36.0M blocks" in text
    assert "MIMALLOC_PURGE_DELAY=0" in text


def test_bytes_per_block_from_the_process_rss():
    text = summarize(_dump(gc=_gc(), process={"rss_bytes": 36_000_000 * 4096}))
    assert "4096 B/block" in text


def test_an_event_loop_stall_overlapping_a_pause_is_named_a_gc_pause():
    latency = {"event_loop": {"max_ms": 113_500.0, "worst_at": AT + 113.9}}
    text = summarize(_dump(gc=_gc(), latency=latency))
    assert "worst event-loop lag 113.5s overlaps a 114.0s GC pause" in text


def test_a_stall_no_pause_overlaps_says_so():
    latency = {"event_loop": {"max_ms": 30_000.0, "worst_at": AT - 3000}}
    text = summarize(_dump(gc=_gc(), latency=latency))
    assert "no recorded GC pause overlaps the worst event-loop lag" in text


def test_no_gc_section_prints_nothing_about_it():
    assert "Garbage collector" not in summarize(_dump())


def test_a_scheduled_collector_says_how_often_it_collected():
    policy = {"active": True, "interval_sec": 300, "collections": 4, "total_ms": 1200.0,
              "last_ms": 250.0, "last_at": AT}
    text = summarize(_dump(gc=_gc(enabled=False, policy=policy)))
    assert "automatic collection off: collected 4 times after a publish" in text
    assert "every 300s at most, 1.2s paused, last 250ms" in text


def test_an_inactive_policy_adds_nothing():
    policy = {"active": False, "interval_sec": 300, "collections": 0, "total_ms": 0.0,
              "last_ms": None, "last_at": None}
    assert "after a publish" not in summarize(_dump(gc=_gc(policy=policy)))
