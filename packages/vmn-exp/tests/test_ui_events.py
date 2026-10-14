"""ui.live_events: what one SSE stream of an app's changes says, and when
(plan 23 S5) — the snapshot diff, scope, coalescing, heartbeat, live ticks
and the stream cap, on a fake clock."""
import asyncio
import json

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.ui.live_events import StreamSlots, event_stream, snapshot_change

from vmn_exp.ui import live_events


def _row(verstr, parent=None):
    return {"verstr": verstr, "parent": parent}


def _snap(rows, states=None, generation=1):
    return IndexSnapshot.build("app", generation, rows, states or {})


def _next(old, changed=(), added=(), removed=(), states=None, generation=None):
    """*old* at its next generation: the *changed* verstrs get new row
    objects, *added* rows join, *removed* verstrs leave."""
    rows = [dict(r) if r["verstr"] in changed else r
            for r in old.rows if r["verstr"] not in removed]
    run_states = dict(old.run_states)
    run_states.update(states or {})
    return _snap(rows + list(added), run_states, generation or old.generation + 1)


def test_changed_added_and_removed_rows_are_counted_with_their_jobs():
    old = _snap([_row("a"), _row("a1", "a"), _row("b"), _row("c")])
    new = _next(old, changed=["a1"], added=[_row("d", "b")], removed=["c"])

    change = snapshot_change(old, new)

    assert change == {"rows": 3, "jobs": ["a", "b", "c"]}


def test_rows_kept_as_the_same_objects_are_not_changed():
    old = _snap([_row("a"), _row("b")], {"a": {"exit_code": None}})
    same = _next(old)

    assert snapshot_change(old, same) == {"rows": 0, "jobs": []}


def test_a_moved_run_state_changes_its_row():
    old = _snap([_row("a"), _row("a1", "a")], {"a1": {"exit_code": None}})
    new = _next(old, states={"a1": {"exit_code": 0}})

    assert snapshot_change(old, new) == {"rows": 1, "jobs": ["a"]}


def test_a_scope_sees_only_its_subtree():
    old = _snap([_row("a"), _row("a1", "a"), _row("a11", "a1"), _row("b")])
    outside = _next(old, changed=["b"])
    inside = _next(old, changed=["a11", "b"])

    assert snapshot_change(old, outside, scope="a1") is None
    assert snapshot_change(old, inside, scope="a1") == {"rows": 1, "jobs": ["a"]}
    assert snapshot_change(old, inside, scope="a11") == {"rows": 1, "jobs": ["a"]}
    assert snapshot_change(old, inside, scope="top") == {"rows": 2, "jobs": ["a", "b"]}


def test_too_many_jobs_are_left_out(monkeypatch):
    monkeypatch.setattr(live_events, "MAX_JOBS", 2)
    old = _snap([_row("a"), _row("b"), _row("c")])
    new = _next(old, changed=["a", "b", "c"])

    assert snapshot_change(old, new) == {"rows": 3}


def test_slots_are_bounded_and_given_back():
    slots = StreamSlots(2)
    assert slots.acquire() and slots.acquire()
    assert not slots.acquire()
    slots.release()
    assert slots.acquire()
    assert slots.active == 2


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, sec):
        self.now += sec


def _collect(timeline, clock, scope=None, max_sec=60):
    """``[(time, kind, payload)]`` of a stream reading *timeline*
    (``[(from time, snapshot)]``) until *max_sec*."""

    async def read():
        return [snap for at, snap in timeline if at <= clock.now][-1]

    async def run():
        out = []
        async for chunk in event_stream(read, scope=scope, clock=clock, sleep=clock.sleep,
                                        max_sec=max_sec):
            out.append((clock.now,) + _parse(chunk))
        return out

    return asyncio.run(run())


def _parse(chunk):
    assert chunk.endswith("\n\n")
    lines = chunk[:-2].split("\n")
    if lines[0].startswith(":"):
        return "comment", lines[0][1:].strip()
    fields = dict(line.split(": ", 1) for line in lines)
    return fields.get("event", "message"), json.loads(fields["data"]) if "data" in fields else fields


def test_a_stream_opens_with_a_retry_hint_and_its_generation():
    clock = _Clock()
    snap = _snap([_row("a")], generation=7)

    events = _collect([(0, snap)], clock, max_sec=5)

    first = events[0]
    assert first[1] == "hello" and first[2]["generation"].startswith("7")
    assert all(kind != "change" for _, kind, _ in events)


def test_a_new_generation_emits_one_change_event():
    clock = _Clock()
    old = _snap([_row("a"), _row("a1", "a")])
    new = _next(old, changed=["a1"])

    events = _collect([(0, old), (2.5, new)], clock, max_sec=6)

    changes = [(at, data) for at, kind, data in events if kind == "change"]
    assert len(changes) == 1
    at, data = changes[0]
    assert 2.5 <= at <= 3.5
    assert data["changed"] == {"rows": 1, "jobs": ["a"]}
    assert data["generation"].startswith(str(new.generation))


def test_changes_are_coalesced_to_one_event_a_second():
    clock = _Clock()
    snaps = [_snap([_row("a")], generation=1)]
    for _ in range(30):
        snaps.append(_next(snaps[-1], changed=["a"]))
    timeline = [(i * 0.2, snap) for i, snap in enumerate(snaps)]

    events = _collect(timeline, clock, max_sec=8)

    times = [at for at, kind, _ in events if kind == "change"]
    assert len(times) >= 5
    assert all(b - a >= 1.0 for a, b in zip(times, times[1:]))


def test_a_change_outside_the_scope_emits_nothing():
    clock = _Clock()
    old = _snap([_row("a"), _row("b")])
    new = _next(old, changed=["b"])

    events = _collect([(0, old), (1, new)], clock, scope="a", max_sec=5)

    assert all(kind != "change" for _, kind, _ in events)


def test_a_quiet_stream_heartbeats_every_25_seconds():
    clock = _Clock()

    events = _collect([(0, _snap([_row("a")]))], clock, max_sec=80)

    beats = [at for at, kind, text in events if kind == "comment" and text == "heartbeat"]
    assert len(beats) == 3
    assert all(abs(b - a - 25) <= 1 for a, b in zip([0] + beats, beats))


def test_live_runs_tick_without_new_generations():
    clock = _Clock()
    live = _snap([_row("a"), _row("a1", "a")], {"a1": {"exit_code": None}})

    events = _collect([(0, live)], clock, max_sec=35)

    ticks = [data for _, kind, data in events if kind == "change"]
    assert len(ticks) == 35 // live_events.LIVE_TICK_SEC
    assert ticks[0]["changed"] == {"rows": 1, "jobs": ["a"]}


def test_finished_runs_do_not_tick():
    clock = _Clock()
    done = _snap([_row("a")], {"a": {"exit_code": 0}})

    events = _collect([(0, done)], clock, max_sec=35)

    assert all(kind != "change" for _, kind, _ in events)


def test_the_stream_ends_after_its_lifetime():
    clock = _Clock()

    _collect([(0, _snap([_row("a")]))], clock, max_sec=12)

    assert 12 <= clock.now <= 13
