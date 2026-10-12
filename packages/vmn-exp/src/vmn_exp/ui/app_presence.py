#!/usr/bin/env python3
"""Whether an app exists in a workspace, asked of the checkout and the store
directly (never the cached app list): its ``.vmn/<app>/conf.yml`` in a git
checkout, else any run or snapshot record."""
import os

from vmn_exp.storage.areas import SNAPSHOTS


def _configured(ws, app_name):
    return ws.kind == "git" and os.path.isfile(
        os.path.join(ws.path, ".vmn", *app_name.split("/"), "conf.yml")
    )


def app_exists(ws, app_name, storage):
    """*storage* is the workspace's run storage (the checkout's local store
    in a git workspace)."""
    if _configured(ws, app_name) or storage.list_verstrs(app_name):
        return True
    return bool(storage.in_area(SNAPSHOTS).list_verstrs(app_name))
