#!/usr/bin/env python3
"""Thread limiters that never lend more tokens than they hold.

Before anyio 4.15 a release wakes the next waiter without giving it the
token: a newcomer arriving before that waiter runs takes the free token too,
and both borrow it, so under load the pool runs past its size (41-44 of 40).
anyio 4.15 hands the token to the woken waiter (the last anyio for Python
3.9 is 4.12); :class:`HandOffLimiter` does the same on older anyio.
:func:`install_default_limiter` (at startup, on the serving loop) makes one
the loop's default limiter, the one sync routes and dependencies run on.
Delete this module once anyio 4.15 is the floor.
"""
import asyncio
import re
from importlib.metadata import version

from anyio import CapacityLimiter, WouldBlock, to_thread
from anyio._backends import _asyncio

ANYIO_HANDS_OFF = tuple(map(int, re.match(r"(\d+)\.(\d+)", version("anyio")).groups())) >= (4, 15)


class HandOffLimiter(_asyncio.CapacityLimiter):
    """anyio 4.15's limiter: a released token goes to the next waiter."""

    async def acquire_on_behalf_of(self, borrower):
        await _asyncio.AsyncIOBackend.checkpoint_if_cancelled()
        try:
            self.acquire_on_behalf_of_nowait(borrower)
        except WouldBlock:
            event = asyncio.Event()
            self._wait_queue[borrower] = event
            try:
                await event.wait()
            except BaseException:
                self._wait_queue.pop(borrower, None)
                if event.is_set():  # handed a token it no longer takes
                    self.release_on_behalf_of(borrower)
                raise
        else:
            try:
                await _asyncio.AsyncIOBackend.cancel_shielded_checkpoint()
            except BaseException:
                self.release_on_behalf_of(borrower)
                raise

    def release_on_behalf_of(self, borrower):
        try:
            self._borrowers.remove(borrower)
        except KeyError:
            raise RuntimeError(
                "this borrower isn't holding any of this CapacityLimiter's tokens") from None
        if self._wait_queue and len(self._borrowers) < self._total_tokens:
            waiter, event = self._wait_queue.popitem(last=False)
            self._borrowers.add(waiter)
            event.set()


def capacity_limiter(total_tokens):
    """A limiter of *total_tokens* for the running loop."""
    return CapacityLimiter(total_tokens) if ANYIO_HANDS_OFF else HandOffLimiter(total_tokens)


def install_default_limiter():
    """Replace the running loop's default thread limiter with a hand-off one
    of the same size (call it on the loop before any thread runs)."""
    if not ANYIO_HANDS_OFF:
        size = to_thread.current_default_thread_limiter().total_tokens
        _asyncio._default_thread_limiter.set(HandOffLimiter(size))
