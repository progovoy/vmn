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


def _dep_list(conf):
    """Flatten nested ``deps`` config into ``[{path, remote, vcs_type, branch}]``."""
    result = []
    for base_dir, repos in (conf.get("deps") or {}).items():
        for repo_name, info in (repos or {}).items():
            info = info or {}
            path = os.path.normpath(os.path.join(base_dir, repo_name))
            result.append({
                "path": path,
                "remote": info.get("remote"),
                "vcs_type": info.get("vcs_type"),
                "branch": info.get("branch"),
            })
    return sorted(result, key=lambda d: d["path"])


def app_config(root_path, app_name):
    """App config for the UI: the raw conf plus a flattened deps list."""
    conf = read_app_conf(root_path, app_name)
    return {"conf": conf, "deps": _dep_list(conf)}
