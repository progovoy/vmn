#!/usr/bin/env python3
"""Read-side access to an app's vmn configuration (conf.yml)."""
import os

import yaml


def read_app_conf(root_path, app_name):
    """The ``conf`` section of ``.vmn/<app>/conf.yml``, or ``{}`` when absent."""
    conf_path = os.path.join(
        root_path, ".vmn", app_name.replace("/", os.sep), "conf.yml"
    )
    try:
        with open(conf_path) as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        return {}
    return data.get("conf", {}) or {}
