#!/usr/bin/env python3
"""Read-side access to an app's vmn configuration: the conf it loads on the
checkout's branch (its branch conf when one exists, else conf.yml)."""
import os

import git
import version_stamp.api as vmn_api
import yaml
from vmn_exp.ui.readers.branch_conf import app_conf_path
from vmn_exp.ui.readers.versions import list_versions


def read_app_conf(root_path, app_name):
    """The ``conf`` section of the app's conf on the checkout's branch, or
    ``{}`` when absent."""
    return read_conf_file(app_conf_path(root_path, app_name))


def read_conf_file(path):
    """The ``conf`` section of the conf.yml at *path*, or ``{}`` when absent."""
    try:
        with open(path) as f:
            return _parse_conf(f.read())
    except OSError:
        return {}


def read_app_conf_text(root_path, app_name):
    """Raw working-tree text of the app's conf on the checkout's branch, or
    None when absent."""
    try:
        with open(app_conf_path(root_path, app_name)) as f:
            return f.read()
    except OSError:
        return None


def read_app_conf_text_at(root_path, app_name, verstr):
    """Raw text of the conf vmn loaded when it stamped the version (see
    :func:`conf_text_at`), as recorded at the version's tag.

    Returns ``(text, err)``: text is None when the tag predates the conf file,
    err is set when the version itself does not exist.
    """
    row = next((r for r in list_versions(root_path, app_name)
                if r["kind"] == "version" and r["verstr"] == verstr), None)
    if row is None:
        return None, f"Version {verstr} not found"

    repo = git.Repo(root_path, search_parent_directories=True)
    try:
        return conf_text_at(_tag_file_reader(repo, row["tag"]), app_name, row["branch"]), None
    finally:
        repo.close()


def _tag_file_reader(repo, tag):
    def show(path):
        try:
            return repo.git.show(f"{tag}:{path}")
        except git.GitCommandError:
            return None
    return show


def conf_text_at(show, app_name, branch):
    """The text of the first conf vmn loads for *app_name* on *branch* (its
    branch conf, else conf.yml), each repo-relative path read through
    *show* (None when absent); None when there is none."""
    app_dir = "/".join((".vmn", app_name))
    for path in vmn_api.branch_conf_candidates(app_dir, branch):
        text = show(path.replace(os.sep, "/"))
        if text is not None:
            return text
    return None


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
