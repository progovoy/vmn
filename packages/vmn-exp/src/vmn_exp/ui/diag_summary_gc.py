#!/usr/bin/env python3
"""The summary part of the dump's ``gc`` section (:mod:`diag_summary` calls
it): collections and their worst pause, the collector's setup, the
allocator next to RSS, and whether the event loop's worst stall was a GC
pause. Same rules: a part that cannot read its section is skipped."""
import time

from vmn_exp.ui.diag_summary_more import STALL_MS, _dict, _list

SHOWN = 5


def _duration(ms):
    return f"{ms / 1000:.1f}s" if ms >= 1000 else f"{ms:.0f}ms"


def _clock(at):
    return time.strftime("%H:%M:%SZ", time.gmtime(at)) if isinstance(at, (int, float)) else "?"


def _millions(n):
    return f"{n / 1e6:.1f}M"


def _setup(section):
    gil = "GIL" if section.get("gil_enabled", True) else "free-threaded"
    enabled = "enabled" if section.get("enabled", True) else "DISABLED"
    threshold = "/".join(str(t) for t in section.get("threshold") or [])
    return (f"Garbage collector ({gil}, {enabled}, {_millions(section.get('freeze_count', 0))}"
            f" frozen, threshold {threshold}):")


def _totals(section):
    return (f"  {section.get('collections', 0)} collections, "
            f"{_duration(section.get('total_ms', 0))} paused, "
            f"max {_duration(section.get('max_ms', 0))} (gen {section.get('max_generation')} "
            f"at {_clock(section.get('max_at'))}); {section.get('collected', 0)} collected, "
            f"{section.get('uncollectable', 0)} uncollectable")


def _recent(pauses):
    if not pauses:
        return []
    shown = ", ".join(f"{_duration(p.get('ms', 0))} gen {p.get('generation')} at "
                      f"{_clock(p.get('at'))}" for p in pauses[-SHOWN:])
    return [f"  recent: {shown}"]


def _allocator(section, process):
    alloc = _dict(section.get("allocator"))
    if not alloc:
        return []
    blocks = alloc.get("allocated_blocks") or 0
    rss = process.get("rss_bytes")
    line = f"  allocator {alloc.get('name')}: {_millions(blocks)} blocks"
    if isinstance(rss, (int, float)) and blocks:
        line += f", rss {rss / 2**30:.1f} GiB ({rss / blocks:.0f} B/block)"
    env = ", ".join(f"{k}={v}" for k, v in _dict(alloc.get("env")).items())
    return [line + (f"; {env}" if env else "")]


def _overlapping(pauses, lag_ms, lag_end):
    lag_start = lag_end - lag_ms / 1000
    return [p for p in pauses
            if p.get("at", 0) < lag_end and p.get("at", 0) + p.get("ms", 0) / 1000 > lag_start]


def _stall(pauses, sections):
    loop = _dict(_dict(sections.get("latency")).get("event_loop"))
    lag_ms, lag_end = loop.get("max_ms") or 0, loop.get("worst_at")
    if lag_ms < STALL_MS or not isinstance(lag_end, (int, float)):
        return []
    hits = _overlapping(pauses, lag_ms, lag_end)
    if not hits:
        return ["  no recorded GC pause overlaps the worst event-loop lag"]
    worst = max(hits, key=lambda p: p.get("ms", 0))
    return [f"  the worst event-loop lag {_duration(lag_ms)} overlaps a "
            f"{_duration(worst.get('ms', 0))} GC pause (gen {worst.get('generation')})"]


def gc_part(sections):
    section = _dict(sections.get("gc"))
    if not section or section.get("error"):
        return []
    pauses = _list(section.get("recent"))
    return ([_setup(section), _totals(section)] + _recent(pauses)
            + _allocator(section, _dict(sections.get("process"))) + _stall(pauses, sections))
