"""The IO ports vmn-exp logic takes as parameters (CLAUDE.md "IO behind interfaces").

Stdlib only. The ports shared with core vmn (``Clock``, ``Env``, ``Processes``,
``Random``, ``Console``) duplicate ``version_stamp.core.ports`` under the same
names and signatures, because the SDK may not import ``version_stamp``;
packages/vmn-exp/tests/test_ports_parity.py keeps the two in step. ``Host``
and ``Processes.popen`` are vmn-exp's own. The real implementations are in
``vmn_exp.core.real_io``; the fakes in the repo's tests/fakes/.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The wall-clock time, timezone-aware in UTC."""

    def monotonic(self) -> float:
        """Seconds on a clock that never goes back."""

    def sleep(self, sec: float) -> None: ...


class Env(Protocol):
    """A read-only mapping of environment variables."""

    def __getitem__(self, key: str) -> str: ...

    def __contains__(self, key: object) -> bool: ...

    def __iter__(self) -> Iterator[str]: ...

    def __len__(self) -> int: ...

    def get(self, key: str, default: str | None = None) -> str | None: ...


class Processes(Protocol):
    def run(self, cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
        """Like ``subprocess.run``: a missing binary raises FileNotFoundError and
        an expired ``timeout`` raises subprocess.TimeoutExpired."""

    def popen(self, cmd: Sequence[str], **kwargs: Any) -> subprocess.Popen: ...


class Random(Protocol):
    def hex_id(self) -> str:
        """32 hex characters."""

    def token_hex(self, nbytes: int) -> str: ...

    def token_urlsafe(self, nbytes: int) -> str: ...

    def token_bytes(self, nbytes: int) -> bytes: ...


class Host(Protocol):
    def pid(self) -> int: ...

    def hostname(self) -> str: ...


class Console(Protocol):
    def out(self, text: str) -> None:
        """Write *text* and a newline to standard output."""

    def err(self, text: str) -> None:
        """Write *text* and a newline to standard error."""

    def read_line(self) -> str:
        """The next input line without its newline; "" at end of input."""


@dataclass(frozen=True)
class IO:
    clock: Clock
    env: Env
    processes: Processes
    random: Random
    host: Host
    console: Console
