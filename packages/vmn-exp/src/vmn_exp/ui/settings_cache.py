"""Apps' store settings (:mod:`vmn_exp.core.app_settings_store`) per
workspace, for the server's read paths."""
import time

from vmn_exp.core.app_settings_store import read_settings
from vmn_exp.storage.areas import app_key
from vmn_exp.ui.memo import LRU


class SettingsCache:
    """Apps' settings read at most every *recheck_sec* (0: every time) unless
    :meth:`forget` drops them first — what a journal entry does."""

    def __init__(self, recheck_sec, clock=time.monotonic, size=256):
        self._recheck_sec, self._clock = recheck_sec, clock
        self._entries = LRU(size)  # (scope, app name) -> (read at, settings)

    def get(self, scope, storage, app_name):
        return self._entries.get(
            (scope, app_name),
            lambda: (self._clock(), read_settings(storage, app_name)),
            valid=lambda hit: self._clock() - hit[0] < self._recheck_sec,
        )[1]

    def forget(self, scope, key=None):
        """Drop *scope*'s entries (only the app of tag-form *key*, if given)."""
        self._entries.drop_where(
            lambda k: k[0] == scope and key in (None, app_key(k[1])))
