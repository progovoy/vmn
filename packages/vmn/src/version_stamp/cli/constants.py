#!/usr/bin/env python3
"""CLI-level constants and data structures."""
from version_stamp.core.constants import (
    GLOBAL_LOG_FILENAME,
    LOCK_FILENAME,
)
from version_stamp.core.models import AppConf
from version_stamp.devversion.untracked import _UNTRACKED_CACHE_FILE

INIT_FILENAME = "conf.yml"
LOG_FILENAME = "vmn.log"
CACHE_FILENAME = "vmn.cache"

IGNORED_FILES = [
    LOCK_FILENAME,
    f"{LOG_FILENAME}*",
    CACHE_FILENAME,
    GLOBAL_LOG_FILENAME,
    _UNTRACKED_CACHE_FILE,
    "*/snapshots/",
    "*/experiments/",
]

VMN_ARGS = {
    "init": "remote",
    "init-app": "remote",
    "show": "local",
    "stamp": "remote",
    "goto": "local",
    "release": "remote",
    "gen": "local",
    "add": "remote",
    "config": "local",
    "worktrees": "local",
    "skill": "local",
    "snapshot": "local",
}

_CONFIG_DESCRIPTIONS = AppConf.config_descriptions()

_ROOT_CONFIG_DESCRIPTIONS = {
    "external_services": {
        "description": "External services tracked by the root app.",
        "type": "nested_dict",
        "nested_key": "external_services",
    },
}


# `vmn worktrees` (alias `vmn wt`) actions, and those that need a name.
WORKTREES_ACTIONS = ("create", "list", "remove", "freeze", "pull")
WORKTREES_NAME_REQUIRED = frozenset({"create", "remove", "freeze"})

# `vmn snapshot` actions (create is the default).
SNAPSHOT_ACTIONS = ("create", "list", "show", "note", "diff", "export", "restore", "delete")
# Built-in commands' actions that never mutate the checkout, so run lock-free.
READ_ONLY_ACTIONS = {"snapshot": frozenset({"list", "show", "diff", "export"})}
