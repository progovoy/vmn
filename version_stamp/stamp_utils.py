#!/usr/bin/env python3
"""Backward-compatible shim — re-exports from version_stamp.core / backends.

All real code now lives in:
  version_stamp.core.constants
  version_stamp.core.models
  version_stamp.core.logging
  version_stamp.core.utils
  version_stamp.core.version_math
  version_stamp.backends.*
"""

# -- constants ----------------------------------------------------------------
from version_stamp.core.constants import (  # noqa: F401
    BOLD_CHAR,
    CONVENTIONAL_COMMIT_PATTERN,
    END_CHAR,
    GLOBAL_LOG_FILENAME,
    INIT_COMMIT_MESSAGE,
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    SEMVER_BUILDMETADATA_REGEX,
    SUPPORTED_REGEX_VARS,
    VMN_BE_TYPE_GIT,
    VMN_BE_TYPE_LOCAL_FILE,
    VMN_OLD_TEMPLATE,
    VMN_TEMPLATE_REGEX,
    VMN_VERSION_FORMAT,
    VMN_VERSTR_REGEX,
    _VMN_VERSION_REGEX,
)

# -- models -------------------------------------------------------------------
from version_stamp.core.models import (  # noqa: F401
    AppConf,
    TagProps,
    VersionProps,
    VMN_DEFAULT_CONF,
)

# -- logging ------------------------------------------------------------------
from version_stamp.core.logging import (  # noqa: F401
    VMN_LOGGER,
    init_stamp_logger,
    measure_runtime_decorator,
)
import version_stamp.core.logging as _logging_module

# -- utils --------------------------------------------------------------------
from version_stamp.core.utils import (  # noqa: F401
    WrongTagFormatException,
    _clean_split_result,
    comment_out_jinja,
    resolve_root_path,
)

# -- version_math -------------------------------------------------------------
from version_stamp.core.version_math import (  # noqa: F401
    compare_release_modes,
    parse_conventional_commit_message,
)

# -- backends -----------------------------------------------------------------
from version_stamp.backends.base import VMNBackend  # noqa: F401
from version_stamp.backends.factory import get_client  # noqa: F401
from version_stamp.backends.git import GitBackend  # noqa: F401
from version_stamp.backends.local_file import LocalFileBackend  # noqa: F401

# -- dataclass helpers re-export (tests use `from dataclasses import fields`) --
from dataclasses import fields  # noqa: F401

# -- runtime context (legacy stamp_utils.call_count) --------------------------
from version_stamp.core.logging import _runtime_ctx  # noqa: F401

call_count = _runtime_ctx.call_count


# Propagate writes to VMN_LOGGER back to the canonical location so that
# tests doing ``stamp_utils.VMN_LOGGER = None`` still work.
# Python < 3.12 doesn't support module __setattr__, so we replace the
# module object with a subclass that intercepts attribute writes.
from version_stamp.core.logging import _logger_holder as _logger_holder  # noqa: F401
import sys as _sys
import types as _types


class _StampUtilsModule(_types.ModuleType):
    """Module subclass that intercepts ``stamp_utils.VMN_LOGGER = X``."""

    def __setattr__(self, name, value):
        if name == "VMN_LOGGER":
            _logger_holder[0] = value
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name):
        if name == "VMN_LOGGER":
            return _logger_holder[0]
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Swap the module object in sys.modules
_self = _sys.modules[__name__]
_new = _StampUtilsModule(__name__, _self.__doc__)
_new.__dict__.update({k: v for k, v in _self.__dict__.items() if k != "VMN_LOGGER"})
_new.__file__ = _self.__file__
_new.__package__ = _self.__package__
_new.__path__ = getattr(_self, "__path__", None)
_new.__spec__ = _self.__spec__
_sys.modules[__name__] = _new
