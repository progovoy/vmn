"""Apps' store settings (:mod:`vmn_exp.core.app_settings_store`) per
workspace, for the server's read paths."""
import contextlib
import contextvars
import time

from vmn_exp.core.app_settings_store import read_settings
from vmn_exp.storage.areas import app_key
from vmn_exp.ui.memo import LRU

_REQUEST = contextvars.ContextVar("vmn_settings_request", default=None)


@contextlib.contextmanager
def request_scope():
    """Mark one request: a zero-window cache reads an app's settings once in it."""
    token = _REQUEST.set(object())
    try:
        yield
    finally:
        _REQUEST.reset(token)


class SettingsCache:
    """Apps' settings read at most every *recheck_sec* (0: once per
    :func:`request_scope`, else every time) unless :meth:`forget` drops them
    first — what a journal entry does."""

    def __init__(self, recheck_sec, clock=time.monotonic, size=256):
        self._recheck_sec, self._clock = recheck_sec, clock
        self._entries = LRU(size)  # (scope, app name) -> (read at, request, settings)

    def get(self, scope, storage, app_name):
        return self._entries.get(
            (scope, app_name),
            lambda: (self._clock(), _REQUEST.get(), read_settings(storage, app_name)),
            valid=self._valid,
        )[2]

    def _valid(self, hit):
        if self._recheck_sec == 0:
            return hit[1] is not None and hit[1] is _REQUEST.get()
        return self._clock() - hit[0] < self._recheck_sec

    def forget(self, scope, key=None):
        """Drop *scope*'s entries (only the app of tag-form *key*, if given)."""
        self._entries.drop_where(
            lambda k: k[0] == scope and key in (None, app_key(k[1])))
