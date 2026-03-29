#!/usr/bin/env python3
"""CLI-level constants and data structures."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from version_stamp.core.constants import GLOBAL_LOG_FILENAME, VER_FILE_NAME  # noqa: F401
from version_stamp.core.models import AppConf

LOCK_FILE_ENV = "VMN_LOCK_FILE_PATH"
INIT_FILENAME = "conf.yml"
LOCK_FILENAME = "vmn.lock"
LOG_FILENAME = "vmn.log"
CACHE_FILENAME = "vmn.cache"

IGNORED_FILES = [
    LOCK_FILENAME,
    f"{LOG_FILENAME}*",
    CACHE_FILENAME,
    GLOBAL_LOG_FILENAME,
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
}

_CONFIG_DESCRIPTIONS = AppConf.config_descriptions()

_ROOT_CONFIG_DESCRIPTIONS = {
    "external_services": {
        "description": "External services tracked by the root app.",
        "type": "nested_dict",
        "nested_key": "external_services",
    },
}


@dataclass
class RepoStatus:
    pending: bool = False
    detached: bool = False
    outgoing: bool = False
    state: Set[str] = field(default_factory=set)
    error: bool = False
    repos_exist_locally: bool = True
    deps_synced_with_conf: bool = True
    repo_tracked: bool = True
    app_tracked: bool = True
    modified: bool = False
    dirty_deps: bool = False
    err_msgs: Dict[str, str] = field(default_factory=lambda: {
        "dirty_deps": "",
        "deps_synced_with_conf": "",
        "repo_tracked": "vmn repo tracking is already initialized",
        "app_tracked": "vmn app tracking is already initialized",
    })
    repos: Dict[str, Any] = field(default_factory=dict)
    matched_version_info: Optional[dict] = None
    local_repos_diff: Set[str] = field(default_factory=set)
