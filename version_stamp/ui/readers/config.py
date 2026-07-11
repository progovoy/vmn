#!/usr/bin/env python3
"""Read-side access to an app's vmn configuration (conf.yml)."""
import os

import git
import yaml

from version_stamp.ui.readers.versions import list_versions


def _conf_relpath(app_name):
    """conf.yml path relative to the repo root (git paths always use '/')."""
    return f".vmn/{app_name}/conf.yml"


def read_app_conf(root_path, app_name):
    """The ``conf`` section of ``.vmn/<app>/conf.yml``, or ``{}`` when absent."""
    return _parse_conf(read_app_conf_text(root_path, app_name))


def read_app_conf_text(root_path, app_name):
    """Raw working-tree conf.yml text, or None when absent."""
    conf_path = os.path.join(root_path, *_conf_relpath(app_name).split("/"))
    try:
        with open(conf_path) as f:
            return f.read()
    except OSError:
        return None


def read_app_conf_text_at(root_path, app_name, verstr):
    """Raw conf.yml text as recorded at the version's tag.

    Returns ``(text, err)``: text is None when the tag predates the conf file,
    err is set when the version itself does not exist.
    """
    tag = None
    for row in list_versions(root_path, app_name):
        if row["kind"] == "version" and row["verstr"] == verstr:
            tag = row["tag"]
            break
    if tag is None:
        return None, f"Version {verstr} not found"

    repo = git.Repo(root_path, search_parent_directories=True)
    try:
        return repo.git.show(f"{tag}:{_conf_relpath(app_name)}"), None
    except git.GitCommandError:
        return None, None
    finally:
        repo.close()


def _parse_conf(text):
    if text is None:
        return {}
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    return data.get("conf", {}) or {}


def app_conf_payload(root_path, app_name, verstr=None):
    """``{"conf": <parsed conf section>, "text": <raw conf.yml or None>}`` for
    the working tree, or as recorded at ``verstr``'s tag when given.

    Returns ``(payload, err)``; err is set when ``verstr`` does not exist.
    """
    if verstr is None:
        text = read_app_conf_text(root_path, app_name)
    else:
        text, err = read_app_conf_text_at(root_path, app_name, verstr)
        if err:
            return None, err
    return {"conf": _parse_conf(text), "text": text}, None
