"""An app's settings in the store: ``settings/<app-key>/app/experiment.yml``.

The file is kept as written (comments too); the record's ``metadata.yml``
says who wrote it last. Reads and writes go to the copy every host shares (a
local-first storage's remote), so a write by one host is the next read of
another; both writes are journaled, so a server following the journal
re-reads within seconds (:mod:`vmn_exp.ui.settings_cache`). See
:mod:`vmn_exp.core.app_settings` for the keys.
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.app_settings import SettingsError, metrics_overlay, parse_settings
from vmn_exp.core.identity import actor_identity
from vmn_exp.core.record_format import stamped
from vmn_exp.registry.fold import now_iso
from vmn_exp.storage.areas import SETTINGS
from vmn_exp.storage.store_marker import authoritative

RECORD = "app"
SETTINGS_FILE = "experiment.yml"


def settings_area(storage):
    """The shared copy of *storage*'s root's ``settings`` area."""
    return authoritative(storage).in_area(SETTINGS)


def _readable_area(storage):
    """The settings area, or None for a storage without store areas (a
    duck-typed or plugin backend that implements only the documented
    SnapshotStorage methods has no settings)."""
    if not hasattr(authoritative(storage), "in_area"):
        return None
    try:
        return settings_area(storage)
    except NotImplementedError:
        return None


def read_settings_text(storage, app_name):
    """The app's settings file as written, or None."""
    area = _readable_area(storage)
    data = area.load_file(app_name, RECORD, SETTINGS_FILE) if area else None
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
    """Validate *text* (SettingsError) and make it the app's settings."""
    parse_settings(text)
    area = settings_area(storage)
    area.save(app_name, RECORD, stamped({
        "verstr": RECORD, "type": "app_settings", "app": app_name, "updated_at": now_iso(),
        "updated_by": actor or actor_identity(),
    }), {})
    area.save_file(app_name, RECORD, SETTINGS_FILE, text)


def settings_metadata(storage, app_name):
    """Who wrote the app's settings last, and when (``{}`` when never)."""
    area = _readable_area(storage)
    metadata = (area.load_metadata(app_name, RECORD) if area else None) or {}
    return {k: metadata[k] for k in ("updated_at", "updated_by") if k in metadata}


def app_metrics_schema(storage, app_name, conf_metrics):
    """*conf_metrics* over the app's store settings: what a reader sorts and
    summarizes on."""
    return metrics_overlay(read_settings(storage, app_name), conf_metrics)
