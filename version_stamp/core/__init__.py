#!/usr/bin/env python3
"""Core data structures, constants, and pure-function utilities for vmn.

This package has no VCS or I/O dependencies beyond the standard library
(plus ``re`` and ``logging``).
"""

# ── Re-export public API ─────────────────────────────────────────────

from version_stamp.core.constants import (  # noqa: F401
    BOLD_CHAR,
    CONVENTIONAL_COMMIT_PATTERN,
    END_CHAR,
    GIT_CACHE_TTL_MINUTES,
    GLOBAL_LOG_FILENAME,
    INIT_COMMIT_MESSAGE,
    JINJA_TAG_RE,
    LOG_FILE_BACKUP_COUNT,
    LOG_FILE_MAX_BYTES,
    MAX_COMMIT_SEARCH_ITERATIONS,
    POOL_SIZE_CLONES,
    POOL_SIZE_UPDATES,
    PUBLISH_MAX_RETRIES,
    PUBLISH_RETRY_SLEEP_SECONDS,
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    SEMVER_BUILDMETADATA_REGEX,
    SUPPORTED_REGEX_VARS,
    TAG_CHRONOLOGICAL_SPACING_SECONDS,
    VMN_BASE_VERSION_REGEX,
    VMN_BE_TYPE_GIT,
    VMN_BE_TYPE_LOCAL_FILE,
    VMN_OLD_REGEX,
    VMN_OLD_TAG_REGEX,
    VMN_OLD_TEMPLATE,
    VMN_ROOT_TAG_REGEX,
    VMN_ROOT_VERSION_REGEX,
    VMN_TAG_REGEX,
    VMN_TEMPLATE_REGEX,
    VMN_USER_NAME,
    VMN_VERSION_FORMAT,
    VMN_VERSION_REGEX,
    VMN_VERSTR_REGEX,
    _VMN_VERSION_REGEX,
)
from version_stamp.core.logging import (  # noqa: F401
    LevelFilter,
    VMN_LOGGER,
    clear_logger_handlers,
    get_call_stack,
    init_log_file_handler,
    init_stamp_logger,
    measure_runtime_decorator,
    reset_runtime_context,
)
from version_stamp.core.models import (  # noqa: F401
    AppConf,
    TagProps,
    VMN_DEFAULT_CONF,
    VersionProps,
)
from version_stamp.core.utils import (  # noqa: F401
    WrongTagFormatException,
    _clean_split_result,
    comment_out_jinja,
    resolve_root_path,
)
from version_stamp.core.version_math import (  # noqa: F401
    app_name_to_tag_name,
    compare_release_modes,
    deserialize_tag_name,
    deserialize_vmn_tag_name,
    deserialize_vmn_version,
    gen_unique_id,
    get_base_vmn_version,
    get_root_app_name_from_name,
    get_utemplate_formatted_version,
    parse_conventional_commit_message,
    serialize_vmn_base_version,
    serialize_vmn_tag_name,
    serialize_vmn_version,
    tag_name_to_app_name,
)
