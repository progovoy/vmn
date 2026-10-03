#!/usr/bin/env python3
"""A finished run's writer compacts its metric stream (plan 12 §6) inside
the final-upload window: past the deadline the stream stays, and readers
(or a later ``vmn-exp compact``) use it."""
import logging
import threading
import time

from vmn_exp.core.metric_compact import compact_writer, record_rewinds
from vmn_exp.core.metric_compact import reopen_writer as _reopen

_LOGGER = logging.getLogger(__name__)


def _compact(storage, app_name, verstr, writer_id):
    try:
        rewinds = record_rewinds(storage, app_name, verstr)
        compact_writer(storage, app_name, verstr, writer_id, rewinds)
    except Exception:
        _LOGGER.debug("Metric compaction failed; the stream stays", exc_info=True)


def compact_by(storage, app_name, verstr, writer_id, deadline):
    """Compact *writer_id*'s stream, waiting until *deadline* (monotonic);
    True when it finished in time."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    worker = threading.Thread(target=_compact, args=(storage, app_name, verstr, writer_id),
                              name="vmn-metric-compact", daemon=True)
    worker.start()
    worker.join(remaining)
    return not worker.is_alive()


def reopen_writer(storage, app_name, verstr, writer_id):
    """Best effort: a resumed run streams on after its writer's ``.vmx``."""
    try:
        _reopen(storage, app_name, verstr, writer_id)
    except Exception:
        _LOGGER.warning(f"vmn: could not reopen run {verstr}'s compacted metrics",
                        exc_info=True)
