#!/usr/bin/env python3
"""An app's metrics schema, re-read only when its conf.yml changes.

Every leaderboard request needs the schema (sort direction, primary metric);
parsing the YAML each time would dominate a memoized list poll. A ``stat`` is
cheap, so the parsed schema is kept per app until the file's
``(mtime, size)`` moves.
"""
import os

from version_stamp.ui.memo import LRU
from version_stamp.ui.readers import experiments as exp_reader
from version_stamp.ui.readers.config import _conf_relpath


def _signature(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class MetricsSchemaCache:
    def __init__(self, size=256):
        self._entries = LRU(size)  # (root, app) -> (conf signature, schema)

    def get(self, root_path, app_name):
        path = os.path.join(root_path, *_conf_relpath(app_name).split("/"))
        # Stat before reading: a write in between is caught by the next stat.
        signature = _signature(path)
        return self._entries.get(
            (root_path, app_name),
            lambda: (signature, exp_reader.metrics_schema(root_path, app_name)),
            valid=lambda hit: hit[0] == signature,
        )[1]
