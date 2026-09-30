"""Run tasks concurrently while keeping their results and log output in the
serial, input order: each task's VMN_LOGGER records are held back and
replayed by the caller when it consumes that task's result."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from version_stamp.core.logging import VMN_LOGGER


class _PerThreadBuffer(logging.Filter):
    """Diverts records logged from a registered thread into its buffer."""

    def __init__(self):
        super().__init__()
        self.buffers = {}

    def filter(self, record):
        buf = self.buffers.get(threading.get_ident())
        if buf is None:
            return True
        buf.append(record)
        return False


def replay(records):
    for record in records:
        VMN_LOGGER.handle(record)


def run_ordered(tasks, max_workers):
    """``[(result, held_log_records), ...]`` of the no-arg *tasks*, in input
    order; the caller replays each task's records via ``replay``."""
    buffering = _PerThreadBuffer()

    def call(task):
        ident = threading.get_ident()
        held = buffering.buffers[ident] = []
        try:
            return task(), held
        finally:
            del buffering.buffers[ident]

    VMN_LOGGER.addFilter(buffering)
    try:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            return list(pool.map(call, tasks))
    finally:
        VMN_LOGGER.removeFilter(buffering)
