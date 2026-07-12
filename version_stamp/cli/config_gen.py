#!/usr/bin/env python3
"""Non-interactive config file generation for `vmn config gen`."""
import dataclasses
import os

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.models import AppConf
from version_stamp.cli.config_tui import (
    _resolve_conf_target,
    _resolve_seeded_branch_conf,
    _write_full_config,
)


def handle_config_gen(vmn_ctx):
    """Create a config file without any TTY interaction.

    Default target is the app's conf.yml seeded from AppConf() defaults;
    --root seeds an empty root conf; --branch (± --root) targets the canonical
    branch conf seeded from the current effective conf. Never overwrites.
    """
    vcs = vmn_ctx.vcs
    if vcs.name is None:
        VMN_LOGGER.error("config gen requires an application name.")
        return 1

    if vmn_ctx.args.branch:
        conf_path, _, raw_conf = _resolve_seeded_branch_conf(
            vmn_ctx, vmn_ctx.args.sync_dep_branches
        )
        if conf_path is None:
            return 1
    elif vmn_ctx.args.root:
        conf_path, _, _ = _resolve_conf_target(vmn_ctx)
        if conf_path is None:
            return 1
        raw_conf = {"external_services": {}}
    else:
        # Always target the default conf.yml, not the branch-resolved conf.
        conf_path = os.path.join(vcs.app_dir_path, "conf.yml")
        raw_conf = dataclasses.asdict(AppConf())

    if os.path.isfile(conf_path):
        VMN_LOGGER.error(f"Config file already exists: {conf_path}")
        return 1

    _write_full_config(conf_path, raw_conf)
    VMN_LOGGER.info(f"Created config file: {conf_path}")
    return 0
