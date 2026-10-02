"""Pure change-journal listing logic (plan 11 §5.2, phase 2b).

Each ``tick()`` lists the minute partitions from ``cursor - skew_window`` to
now, returns keys not seen before grouped by ``(area, app_key)`` scope, and
reports scopes with more than ``max_per_scope`` new entries (the caller does a
full listing for those). Storage-agnostic: ``list_fn(prefix, start_after)``
yields full keys; backends that ignore ``start_after`` are filtered here.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from vmn_exp.core.journal_keys import (
    JournalKey,
    decode_key,
    partition_prefixes,
    time_floor_key,
)

Scope = Tuple[str, str]
ListFn = Callable[[str, Optional[str]], Iterable[str]]


@dataclass
class TickResult:
    entries: Dict[Scope, List[JournalKey]] = field(default_factory=dict)
    overflow: Set[Scope] = field(default_factory=set)


class JournalReader:
    def __init__(self, list_fn: ListFn, clock: Callable[[], float],
                 skew_window_sec: float = 300, max_per_scope: int = 10_000,
                 last_seen_ms: Optional[int] = None):
        self._list = list_fn
        self._clock = clock
        self._skew_ms = int(skew_window_sec * 1000)
        self._max = max_per_scope
        self._last_seen_ms = last_seen_ms
        self._seen: Dict[str, int] = {}

    @classmethod
    def from_cursor(cls, cursor: dict, list_fn: ListFn, clock, **kw):
        return cls(list_fn, clock, last_seen_ms=cursor.get("last_seen_ms"), **kw)

    @property
    def cursor(self) -> dict:
        return {"last_seen_ms": self._last_seen_ms}

    def tick(self) -> TickResult:
        now_ms = int(self._clock() * 1000)
        start_ms = min(self._last_seen_ms or now_ms, now_ms) - self._skew_ms
        self._forget_before(start_ms)
        result = self._group(self._new_keys(start_ms, now_ms))
        self._last_seen_ms = max(self._last_seen_ms or now_ms, now_ms)
        return result

    def _new_keys(self, start_ms: int, now_ms: int) -> List[JournalKey]:
        floor = time_floor_key(start_ms)
        found = []
        for prefix in partition_prefixes(start_ms, now_ms):
            start_after = floor if floor.startswith(prefix) else None
            for raw in self._list(prefix, start_after):
                key = self._accept(raw, floor)
                if key is not None:
                    found.append(key)
        found.sort(key=lambda k: k.unix_ms)
        return found

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
            del result.entries[scope]
            result.overflow.add(scope)
        return result
