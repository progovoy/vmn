"""Change-journal object keys (plan 11 §5.2).

``journal/<YYYYMMDDHHMM>/<unix_ms:013d>_<area>_<app-key>_<writer_id>_<seq>_<name>``
with every field percent-encoded so ``_`` and ``/`` never appear raw.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote, unquote

JOURNAL_PREFIX = "journal/"
_MINUTE_MS = 60_000


@dataclass(frozen=True)
class JournalKey:
    unix_ms: int
    area: str
    app_key: str
    writer_id: str
    seq: int
    name: str

    @property
    def scope(self):
        return (self.area, self.app_key)


def _enc(value) -> str:
    return quote(str(value), safe="").replace("_", "%5F")


def partition_of(unix_ms: int) -> str:
    moment = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)
    return moment.strftime("%Y%m%d%H%M")


def partition_prefix(unix_ms: int) -> str:
    return f"{JOURNAL_PREFIX}{partition_of(unix_ms)}/"


def partition_prefixes(start_ms: int, end_ms: int) -> List[str]:
    """Prefixes of every minute partition from ``start_ms`` to ``end_ms``."""
    first = start_ms - start_ms % _MINUTE_MS
    return [partition_prefix(m) for m in range(first, end_ms + 1, _MINUTE_MS)]


def time_floor_key(unix_ms: int) -> str:
    """A ``start_after`` bound that keeps every key at or after ``unix_ms``."""
    return f"{partition_prefix(unix_ms)}{unix_ms:013d}"


def encode_key(key: JournalKey) -> str:
    fields = [f"{key.unix_ms:013d}", key.area, key.app_key,
              key.writer_id, str(key.seq), key.name]
    return partition_prefix(key.unix_ms) + "_".join(_enc(f) for f in fields)


def decode_key(full_key: str) -> Optional[JournalKey]:
    parts = full_key.split("/")
    if len(parts) != 3 or f"{parts[0]}/" != JOURNAL_PREFIX:
        return None
    fields = [unquote(f) for f in parts[2].split("_")]
    if len(fields) != 6 or not fields[0].isdigit() or not fields[4].isdigit():
        return None
    ms, area, app_key, writer_id, seq, name = fields
    return JournalKey(int(ms), area, app_key, writer_id, int(seq), name)
