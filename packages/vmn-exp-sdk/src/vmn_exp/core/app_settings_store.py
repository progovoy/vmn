"""An app's settings in the store: ``settings/<app-key>/app/experiment.yml``.

The file is kept as written (comments too); the record's ``metadata.yml``
says who wrote it last. Reads and writes go to the copy every host shares (a
local-first storage's remote), so a write by one host is the next read of
another; both writes are journaled, so a server following the journal
re-reads within seconds (:class:`SettingsCache`). See
:mod:`vmn_exp.core.app_settings` for the keys.
"""
import threading
import time

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.app_settings import SettingsError, metrics_overlay, parse_settings
from vmn_exp.core.identity import actor_identity
from vmn_exp.core.record_format import stamped
from vmn_exp.registry.fold import now_iso
from vmn_exp.storage.areas import SETTINGS, app_key
from vmn_exp.storage.store_marker import authoritative

RECORD = "app"
SETTINGS_FILE = "experiment.yml"


def settings_area(storage):
    """The shared copy of *storage*'s root's ``settings`` area."""
    return authoritative(storage).in_area(SETTINGS)


def read_settings_text(storage, app_name):
    """The app's settings file as written, or None."""
    data = settings_area(storage).load_file(app_name, RECORD, SETTINGS_FILE)
    if data is None:
        return None
    return data.decode() if isinstance(data, bytes) else data


def read_settings(storage, app_name):
    """The app's validated settings; ``{}`` when none or unreadable."""
    return _parsed(app_name, read_settings_text(storage, app_name))


def _parsed(app_name, text):
    try:
        return parse_settings(text)
    except SettingsError as exc:
        VMN_LOGGER.warning(f"Ignoring the store settings of {app_name}: {exc}")
        return {}


def write_settings(storage, app_name, text, actor=None):
    """Validate *text* and make it the app's settings; the parsed settings."""
    settings = parse_settings(text)
    area = settings_area(storage)
    area.save(app_name, RECORD, stamped({
        "verstr": RECORD, "type": "app_settings", "app": app_name, "updated_at": now_iso(),
        "updated_by": actor or actor_identity(),
    }), {})
    area.save_file(app_name, RECORD, SETTINGS_FILE, text)
    return settings


def settings_metadata(storage, app_name):
    """Who wrote the app's settings last, and when (``{}`` when never)."""
    metadata = settings_area(storage).load_metadata(app_name, RECORD) or {}
    return {k: metadata[k] for k in ("updated_at", "updated_by") if k in metadata}


def app_metrics_schema(storage, app_name, conf_metrics):
    """*conf_metrics* over the app's store settings: what a reader sorts and
    summarizes on."""
    return metrics_overlay(read_settings(storage, app_name), conf_metrics)


class SettingsCache:
    """Apps' settings read at most every *recheck_sec* (0: every time) unless
    :meth:`forget` drops them first — what a journal entry does."""

    def __init__(self, recheck_sec, clock=time.monotonic):
        self._recheck_sec, self._clock = recheck_sec, clock
        self._entries = {}  # (scope, app name) -> (read at, text, settings)
        self._lock = threading.Lock()

    def get(self, key, storage, app_name):
        with self._lock:
            hit = self._entries.get(key)
        now = self._clock()
        if hit is not None and self._recheck_sec and now - hit[0] < self._recheck_sec:
            return hit[2]
        text = read_settings_text(storage, app_name)
        settings = hit[2] if hit is not None and hit[1] == text else _parsed(app_name, text)
        with self._lock:
            self._entries[key] = (now, text, settings)
        return settings

    def forget(self, scope, key=None):
        """Drop *scope*'s entries (only the app of tag-form *key*, if given)."""
        with self._lock:
            for entry in [k for k in self._entries
                          if k[0] == scope and key in (None, app_key(k[1]))]:
                del self._entries[entry]
