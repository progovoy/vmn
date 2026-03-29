#!/usr/bin/env python3
import re

# ── Version format strings ──────────────────────────────────────────

# Only used for printing
VMN_VERSION_FORMAT = (
    "{major}.{minor}.{patch}[.{hotfix}][-{prerelease}][.{rcn}][+{buildmetadata}]"
)

VMN_OLD_TEMPLATE = (
    "[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][+{buildmetadata}]"
)

INIT_COMMIT_MESSAGE = "Initialized vmn tracking"

# ── Regex patterns ───────────────────────────────────────────────────

_DIGIT_REGEX = r"0|[1-9]\d*"

_SEMVER_BASE_VER_REGEX = (
    rf"(?P<major>{_DIGIT_REGEX})\.(?P<minor>{_DIGIT_REGEX})\.(?P<patch>{_DIGIT_REGEX})"
)

_SEMVER_PRERELEASE_REGEX = rf"(?:-(?P<prerelease>(?:{_DIGIT_REGEX}|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:{_DIGIT_REGEX}|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
_VMN_PRERELEASE_REGEX = (
    rf"{_SEMVER_PRERELEASE_REGEX[:-2]}\.(?P<rcn>(?:{_DIGIT_REGEX})))?"
)
SEMVER_BUILDMETADATA_REGEX = (
    r"(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
)

_VMN_HOTFIX_REGEX = rf"(?:\.(?P<hotfix>{_DIGIT_REGEX}))?"

_VMN_BASE_VER_REGEX = rf"{_SEMVER_BASE_VER_REGEX}{_VMN_HOTFIX_REGEX}"

VMN_BASE_VERSION_REGEX = rf"^{_VMN_BASE_VER_REGEX}$"

# "old" means 0.8.4 format
_VMN_OLD_REGEX = (
    rf"{_VMN_BASE_VER_REGEX}{_SEMVER_PRERELEASE_REGEX}{SEMVER_BUILDMETADATA_REGEX}"
)
VMN_OLD_REGEX = rf"^{_VMN_OLD_REGEX}$"
VMN_OLD_TAG_REGEX = rf"^(?P<app_name>[^\/]+)_{_VMN_OLD_REGEX}$"

VMN_VERSTR_REGEX = rf"{_VMN_BASE_VER_REGEX}{_VMN_PRERELEASE_REGEX}"

_VMN_VERSION_REGEX = rf"{VMN_VERSTR_REGEX}{SEMVER_BUILDMETADATA_REGEX}"
# Regex for matching versions stamped by vmn
VMN_VERSION_REGEX = rf"^{_VMN_VERSION_REGEX}$"
VMN_TAG_REGEX = rf"^(?P<app_name>[^\/]+)_{_VMN_VERSION_REGEX}$"

_VMN_ROOT_REGEX = rf"(?P<version>{_DIGIT_REGEX})"
VMN_ROOT_VERSION_REGEX = rf"^{_VMN_ROOT_REGEX}$"
VMN_ROOT_TAG_REGEX = rf"^(?P<app_name>[^\/]+)_{_VMN_ROOT_REGEX}$"

VMN_TEMPLATE_REGEX = (
    r"^(?:\[(?P<major_template>[^\{\}]*\{major\}[^\{\}]*)\])?"
    r"(?:\[(?P<minor_template>[^\{\}]*\{minor\}[^\{\}]*)\])?"
    r"(?:\[(?P<patch_template>[^\{\}]*\{patch\}[^\{\}]*)\])?"
    r"(?:\[(?P<hotfix_template>[^\{\}]*\{hotfix\}[^\{\}]*)\])?"
    r"(?:\[(?P<prerelease_template>[^\{\}]*\{prerelease\}[^\{\}]*)\])?"
    r"(?:\[(?P<rcn_template>[^\{\}]*\{rcn\}[^\{\}]*)\])?"
    r"(?:\[(?P<buildmetadata_template>[^\{\}]*\{buildmetadata\}[^\{\}]*)\])?$"
)

SUPPORTED_REGEX_VARS = {
    "VMN_VERSION_REGEX": _VMN_VERSION_REGEX,
    "VMN_ROOT_VERSION_REGEX": VMN_ROOT_VERSION_REGEX,
}

CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"""
    ^(?P<type>[a-zA-Z0-9 ]+)              # Commit type (e.g., feat, fix)
    (?:\((?P<scope>[a-zA-Z0-9\-]+)\))?(?P<bc>!)?  # Optional scope
    :\s*(?P<description>.+)            # Description
    (?:\n\n(?P<body>.*))?              # Optional body
    (?:\n\n(?P<footer>.*))?            # Optional footer
    $
""",
    re.VERBOSE | re.DOTALL | re.MULTILINE,
)

# Patterns for live Jinja code we need to protect
JINJA_TAG_RE = re.compile(
    r'(\{\{.*?\}\}|\{%.*?%\})',
    re.DOTALL,
)

# ── Formatting constants ─────────────────────────────────────────────

BOLD_CHAR = "\033[1m"
END_CHAR = "\033[0m"

# ── VCS position types ───────────────────────────────────────────────

RELATIVE_TO_CURRENT_VCS_POSITION_TYPE = "current"
RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE = "branch"
RELATIVE_TO_GLOBAL_TYPE = "global"

# ── Backend types ────────────────────────────────────────────────────

VMN_USER_NAME = "vmn"
VMN_BE_TYPE_GIT = "git"
VMN_BE_TYPE_LOCAL_FILE = "local_file"

# ── Logging ──────────────────────────────────────────────────────────

GLOBAL_LOG_FILENAME = "global_vmn.log"

# ── Magic-number constants ───────────────────────────────────────────

LOG_FILE_MAX_BYTES = 1024 * 1024 * 50
LOG_FILE_BACKUP_COUNT = 1
GIT_CACHE_TTL_MINUTES = 30
TAG_CHRONOLOGICAL_SPACING_SECONDS = 1.1
MAX_COMMIT_SEARCH_ITERATIONS = 1000
PUBLISH_MAX_RETRIES = 5
PUBLISH_RETRY_SLEEP_SECONDS = 60
POOL_SIZE_UPDATES = 10
POOL_SIZE_CLONES = 20
