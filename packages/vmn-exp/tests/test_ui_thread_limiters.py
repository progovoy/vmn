"""The UI's thread limiters never lend more tokens than they hold.

anyio before 4.15 wakes the next waiter on a release without giving it the
token, so a newcomer arriving before the waiter runs takes the token too and
the pool runs past its size (41-44 borrowed of 40 under load).
"""
import asyncio

import anyio
import pytest
from anyio import to_thread, wait_all_tasks_blocked

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.ui.thread_limiters import capacity_limiter


async def _borrowed_after_a_newcomer_races_a_woken_waiter(limiter):
    seats = [object() for _ in range(int(limiter.total_tokens))]
    for seat in seats:
        limiter.acquire_on_behalf_of_nowait(seat)
    holders = list(seats)
    got = anyio.Event()

    async def waiter():
        await limiter.acquire_on_behalf_of("waiter")
        got.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(waiter)
        await wait_all_tasks_blocked()
        limiter.release_on_behalf_of(holders.pop())  # wakes the waiter
        try:
            limiter.acquire_on_behalf_of_nowait("newcomer")  # before it runs
            holders.append("newcomer")
        except anyio.WouldBlock:
            pass
        await got.wait()
    borrowed = limiter.borrowed_tokens
    for holder in holders + ["waiter"]:
        limiter.release_on_behalf_of(holder)
    return borrowed


def test_a_released_token_goes_to_the_woken_waiter_not_a_newcomer():
    async def race():
        return await _borrowed_after_a_newcomer_races_a_woken_waiter(capacity_limiter(3))

    assert anyio.run(race) == 3


def test_a_waiter_cancelled_after_being_handed_a_token_gives_it_back():
    async def cancelled_waiter():
        limiter = capacity_limiter(1)
        limiter.acquire_on_behalf_of_nowait("holder")
        waiter = asyncio.ensure_future(limiter.acquire_on_behalf_of("waiter"))
        await wait_all_tasks_blocked()
        limiter.release_on_behalf_of("holder")  # hands the token over
        waiter.cancel()  # before the waiter runs
        with pytest.raises(asyncio.CancelledError):
            await waiter
        return limiter.borrowed_tokens

    assert anyio.run(cancelled_waiter) == 0


def _manager(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    return WorkspaceManager(str(tmp_path / "data"))


@pytest.mark.parametrize("pool", ["default", "slow_read"])
def test_the_serving_loops_pools_never_lend_past_their_size(tmp_path, pool):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.slow_reads import slow_read_limiter

    limiter_of = {"default": to_thread.current_default_thread_limiter,
                  "slow_read": slow_read_limiter}[pool]

    async def race():
        limiter = limiter_of()
        return limiter.total_tokens, await _borrowed_after_a_newcomer_races_a_woken_waiter(
            limiter)

    with TestClient(create_app(_manager(tmp_path))) as client:
        total, borrowed = client.portal.call(race)
    assert borrowed == total
