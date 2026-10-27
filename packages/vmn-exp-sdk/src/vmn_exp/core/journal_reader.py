"""Pure change-journal listing logic (plan 11 §5.2, phase 2b).

Each ``tick()`` lists the minute partitions from ``cursor - skew_window`` to
now — every ``rescan_sec``; in between only the current and previous minute,
so an idle store costs two listings a tick, and an entry a lagging writer put
in an older minute is read by the next rescan — returns keys not seen before grouped by ``(area, app_key)`` scope, and
reports scopes with more than ``max_per_scope`` new entries, with the record
names they named (the caller catches up on those some cheaper way than one
hint per entry). Storage-agnostic: ``list_fn(prefix, start_after)``
yields full keys; backends that ignore ``start_after`` are filtered here.

A reader resumed from an old cursor lists no further back than
``max_lookback_sec`` (what the journal keeps: older partitions are gone), and
lists its many partitions ``workers`` at a time (a tick's few, the skew
window's, on the calling thread).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from vmn_exp.core.journal_keys import (
    JournalKey,
    decode_key,
    partition_prefixes,
    time_floor_key,
)

# Partitions a tick lists on its own thread: the skew window's and a few more.
SERIAL_PARTITIONS = 16

Scope = Tuple[str, str]
ListFn = Callable[[str, Optional[str]], Iterable[str]]


@dataclass
class TickResult:
    entries: Dict[Scope, List[JournalKey]] = field(default_factory=dict)
    overflow: Set[Scope] = field(default_factory=set)
    overflow_names: Dict[Scope, Set[str]] = field(default_factory=dict)


class JournalReader:
    def __init__(self, list_fn: ListFn, clock: Callable[[], float],
                 skew_window_sec: float = 300, max_per_scope: int = 10_000,
                 last_seen_ms: Optional[int] = None, boundary: Iterable[str] = (),
                 rescan_sec: float = 30, max_lookback_sec: Optional[float] = None,
                 workers: int = 1):
        self._list = list_fn
        self._clock = clock
        self._skew_ms = int(skew_window_sec * 1000)
        self._max = max_per_scope
        self._rescan_ms = int(rescan_sec * 1000)
        self._rescanned_ms = None  # when a tick last listed the whole skew window
        self._lookback_ms = None if max_lookback_sec is None else int(max_lookback_sec * 1000)
        self._workers = workers
        self._last_seen_ms = last_seen_ms
        # Keys at exactly last_seen_ms survive a resume: the next window
        # starts at that ms, so they would be read again.
        self._seen: Dict[str, int] = {k: last_seen_ms for k in boundary}

    @classmethod
    def from_cursor(cls, cursor: dict, list_fn: ListFn, clock, **kw):
        return cls(list_fn, clock, last_seen_ms=cursor.get("last_seen_ms"),
                   boundary=cursor.get("boundary", ()), **kw)

    @property
    def cursor(self) -> dict:
        boundary = sorted(k for k, ms in self._seen.items() if ms >= (self._last_seen_ms or 0))
        cursor = {"last_seen_ms": self._last_seen_ms}
        return {**cursor, "boundary": boundary} if boundary else cursor

    def tick(self) -> TickResult:
        now_ms = int(self._clock() * 1000)
        start_ms = min(self._last_seen_ms or now_ms, now_ms) - self._skew_ms
        if self._lookback_ms is not None:
            start_ms = max(start_ms, now_ms - self._lookback_ms)
        self._forget_before(start_ms)
        result = self._group(self._new_keys(self._listed_from(start_ms, now_ms), now_ms))
        self._last_seen_ms = max(self._last_seen_ms or now_ms, now_ms)
        return result

    def _listed_from(self, start_ms: int, now_ms: int) -> int:
        """*start_ms* when a rescan of the skew window is due, else the start
        of the previous minute."""
        rescanned = self._rescanned_ms
        if rescanned is not None and 0 <= now_ms - rescanned < self._rescan_ms:
            return max(start_ms, now_ms - 60_000)
        self._rescanned_ms = now_ms
        return start_ms

    def _new_keys(self, start_ms: int, now_ms: int) -> List[JournalKey]:
        floor = time_floor_key(start_ms)
        found = []
        for raw in self._listed(partition_prefixes(start_ms, now_ms), floor):
            key = self._accept(raw, floor)
            if key is not None:
                found.append(key)
        found.sort(key=lambda k: k.unix_ms)
        return found

    def _listed(self, prefixes: List[str], floor: str) -> Iterable[str]:
        def listed(prefix):
            return list(self._list(prefix, floor if floor.startswith(prefix) else None))

        if self._workers < 2 or len(prefixes) <= SERIAL_PARTITIONS:
            return (raw for prefix in prefixes for raw in listed(prefix))
        with ThreadPoolExecutor(max_workers=min(self._workers, len(prefixes)),
                                thread_name_prefix="vmn-journal-list") as pool:
            return [raw for keys in pool.map(listed, prefixes) for raw in keys]

    def _accept(self, raw: str, floor: str) -> Optional[JournalKey]:
        if raw <= floor or raw in self._seen:
            return None
        key = decode_key(raw)
        if key is not None:
            self._seen[raw] = key.unix_ms
        return key

    def _forget_before(self, start_ms: int) -> None:
        self._seen = {k: ms for k, ms in self._seen.items() if ms >= start_ms}

    def _group(self, keys: List[JournalKey]) -> TickResult:
        result = TickResult()
        for key in keys:
            result.entries.setdefault(key.scope, []).append(key)
        for scope in [s for s, ks in result.entries.items() if len(ks) > self._max]:
            result.overflow_names[scope] = {key.name for key in result.entries.pop(scope)}
            result.overflow.add(scope)
        return result
