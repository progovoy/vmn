#!/usr/bin/env python3
"""Backward-compatible shim — re-exports from version_stamp.cli / stamping.

All real code now lives in:
  version_stamp.cli.*
  version_stamp.stamping.*
"""

# -- entry / run --------------------------------------------------------------
from version_stamp.cli.entry import (  # noqa: F401
    VMNContainer,
    main,
    validate_app_name,
    vmn_run,
)

# -- cli constants ------------------------------------------------------------
from version_stamp.cli.constants import (  # noqa: F401
    IGNORED_FILES,
    INIT_FILENAME,
    LOCK_FILE_ENV,
    LOCK_FILENAME,
    LOG_FILENAME,
    RepoStatus,
    VER_FILE_NAME,
    VMN_ARGS,
)

# -- command handlers ---------------------------------------------------------
from version_stamp.cli.commands import (  # noqa: F401
    _get_repo_status,
    _init_app,
    _stamp_version,
    handle_add,
    handle_config,
    handle_goto,
    handle_init,
    handle_init_app,
    handle_release,
    handle_show,
    handle_stamp,
    handle_gen,
)

# -- output / display ---------------------------------------------------------
from version_stamp.cli.output import (  # noqa: F401
    _clone_repo,
    _goto_version,
    _handle_output_to_user,
    _handle_root_output_to_user,
    _update_repo,
    gen,
    get_dirty_states,
    goto_version,
    show,
)

# -- args parsing -------------------------------------------------------------
from version_stamp.cli.args import (  # noqa: F401
    parse_user_commands,
    verify_user_input_version,
)

# -- stamping classes ---------------------------------------------------------
from version_stamp.stamping.base import IVersionsStamper  # noqa: F401
from version_stamp.stamping.publisher import VersionControlStamper  # noqa: F401
from version_stamp.stamping.template_data import (  # noqa: F401
    create_data_dict_for_jinja2,
    gen_jinja2_template_from_data,
)
