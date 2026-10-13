#!/usr/bin/env python3
"""An app's metrics schema, re-read only when its conf.yml changes.

Every leaderboard request needs the schema (sort direction, primary metric);
parsing the YAML each time would dominate a memoized list poll. A ``stat`` is
cheap, so the parsed schema is kept per app until the file's
``(mtime, size)`` moves.
"""
import os

from vmn_exp.ui.memo import LRU
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.readers.config import _conf_relpath


def _signature(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _app_conf(root_path, app_name):
    return os.path.join(root_path, *_conf_relpath(app_name).split("/"))


class MetricsSchemaCache:
    """*read(root_path, app_name)* (default: the metrics schema) per change
    of the conf file *path(root_path, app_name)* (default: the app conf)."""

    def __init__(self, size=256, read=None, path=_app_conf):
        self._entries = LRU(size)  # (root, app) -> (conf signature, schema)
        self._read = read
        self._path = path

    def get(self, root_path, app_name):
        path = self._path(root_path, app_name)
        # Stat before reading: a write in between is caught by the next stat.
        signature = (path, _signature(path))
        return self._entries.get(
            (root_path, app_name),
            lambda: (signature, (self._read or exp_reader.metrics_schema)(root_path, app_name)),
            valid=lambda hit: hit[0] == signature,
        )[1]
