"""The change journal's write side (plan 11 §5.2).

:func:`journaled` turns a backend into a :class:`JournaledStorage` of the same
type: each write that changes what a reader sees (claim, metadata, a log batch
or segment, a metric block or ``.vmx``, a file or artifact, the final ``run_state.yml``, a delete) runs on
the backend first and then puts one empty journal entry naming the record.
Heartbeat-only ``run_state.yml`` rewrites put none. A put that still fails
after its retries stays queued and goes out with the next write (or
:meth:`JournaledStorage.flush_journal`, or at exit) — never dropped silently.
"""
import atexit
import itertools
import threading
import time
import weakref

import yaml

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.journal_keys import JOURNAL_PREFIX, JournalKey, encode_key, partition_of
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.areas import app_key
from vmn_exp.storage.journal_sinks import journal_sinks, sink_for

JOURNAL_MAX_AGE_SEC = 2 * 86_400
_SEQ = itertools.count()
_STATES = weakref.WeakSet()


def _default_backoff(attempt):
    time.sleep(min(0.1 * 2 ** attempt, 2.0))


class _JournalState:
    """What every area of one journaled store shares: sink, writer, queue."""

    def __init__(self, sink, writer_id, retries, backoff, clock):
        self.sink, self.writer_id = sink, writer_id
        self.retries, self.backoff, self.clock = retries, backoff, clock
        self.pending = []
        self.lock = threading.Lock()
        self.local = threading.local()
        _STATES.add(self)

    def record(self, area, app_name, name):
        writer = self.writer_id or _writer_id()
        key = JournalKey(int(self.clock() * 1000), area, app_key(app_name),
                         writer, next(_SEQ), name)
        with self.lock:
            self.pending.append(encode_key(key))
        self.flush()

    def flush(self):
        with self.lock:
            keys, self.pending = self.pending, []
        failed = [key for key in keys if not self._put(key)]
        if failed:
            with self.lock:
                self.pending[:0] = failed

    def _put(self, key):
        for attempt in range(self.retries):
            try:
                self.sink.put(key)
                return True
            except Exception:
                if attempt + 1 < self.retries:
                    self.backoff(attempt)
        VMN_LOGGER.debug(f"Journal put {key} failed; queued", exc_info=True)
        return False


def _writer_id():
    from vmn_exp.core.writer import get_writer_id

    return get_writer_id()


def _is_heartbeat(filename, data):
    if filename != RUN_STATE_FILE:
        return False
    try:
        state = yaml.safe_load(data) or {}
    except yaml.YAMLError:
        return False
    return state.get("exit_code") is None and state.get("state") != "finished"


def _journaled_write(name, when=lambda result, args: True):
    def method(self, app_name, record, *args, **kwargs):
        local = self._journal_state.local
        local.depth = getattr(local, "depth", 0) + 1
        try:
            result = getattr(super(JournaledStorage, self), name)(
                app_name, record, *args, **kwargs)
        finally:
            local.depth -= 1
        if local.depth == 0 and when(result, args):
            self._journal_state.record(self.area, app_name, record)
        return result

    method.__name__ = name
    return method


class JournaledStorage:
    """Mixed in front of a backend class by :func:`journaled`."""

    save = _journaled_write("save")
    create_exclusive = _journaled_write("create_exclusive", lambda r, a: bool(r))
    update_metadata = _journaled_write("update_metadata", lambda r, a: r is not False)
    update_note = _journaled_write("update_note")
    save_file = _journaled_write("save_file", lambda r, a: not _is_heartbeat(*a[:2]))
    save_artifact_file = _journaled_write("save_artifact_file")
    append_log_entry = _journaled_write("append_log_entry")
    append_log_entries = _journaled_write("append_log_entries")
    put_log_segment = _journaled_write("put_log_segment")
    append_metric_block = _journaled_write("append_metric_block", lambda r, a: bool(r))
    put_metric_segment = _journaled_write("put_metric_segment")
    put_indexed = _journaled_write("put_indexed", lambda r, a: bool(r))
    delete = _journaled_write("delete")

    @property
    def _journal_sink(self):
        return self._journal_state.sink

    def flush_journal(self):
        self._journal_state.flush()

    def _open_area(self, name):
        opened = super()._open_area(name)
        if isinstance(opened, JournaledStorage):
            return opened
        return _adopt(opened, self._journal_state)


_CLASSES = {}


def _journaled_class(cls):
    if cls not in _CLASSES:
        _CLASSES[cls] = type(f"Journaled{cls.__name__}", (JournaledStorage, cls),
                             {"read_class": cls})
    return _CLASSES[cls]


def _adopt(inner, state):
    wrapped = object.__new__(_journaled_class(type(inner)))
    wrapped.__dict__.update(inner.__dict__)
    wrapped._journal_state = state
    return wrapped


def journaled(inner, sink=None, writer_id=None, retries=3,
              backoff=_default_backoff, clock=time.time):
    """*inner* as a :class:`JournaledStorage` (a backend without a journal
    sink is returned as is)."""
    if isinstance(inner, JournaledStorage):
        return inner
    sink = sink or sink_for(inner)
    if sink is None:
        VMN_LOGGER.debug(f"{type(inner).__name__} has no change journal")
        return inner
    return _adopt(inner, _JournalState(sink, writer_id, retries, backoff, clock))


def prune_journal(storage, now=None, max_age_sec=JOURNAL_MAX_AGE_SEC):
    """Delete *storage*'s journal partitions older than *max_age_sec*."""
    now_ms = int((time.time() if now is None else now) * 1000)
    cutoff = partition_of(now_ms - int(max_age_sec * 1000))
    sinks = journal_sinks(storage) or [s for s in [sink_for(storage)] if s]
    for sink in sinks:
        for prefix in sink.partitions():
            if prefix[len(JOURNAL_PREFIX):].rstrip("/") < cutoff:
                sink.delete_prefix(prefix)


@atexit.register
def _flush_all():
    for state in list(_STATES):
        try:
            state.flush()
        except Exception:
            VMN_LOGGER.debug("Final journal flush failed", exc_info=True)
