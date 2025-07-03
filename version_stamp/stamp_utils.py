#!/usr/bin/env python3
import configparser
import datetime
import glob
import logging
import os
import pathlib
import re
import sys
import time
from functools import wraps
from logging.handlers import RotatingFileHandler

import git
import yaml

INIT_COMMIT_MESSAGE = "Initialized vmn tracking"

# Only used for printing
VMN_VERSION_FORMAT = (
    "{major}.{minor}.{patch}[.{hotfix}][-{prerelease}][.{rcn}][+{buildmetadata}]"
)

VMN_DEFAULT_CONF = {
    "template": "[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][.{rcn}][+{buildmetadata}]",
    "old_template": "[{major}][.{minor}][.{patch}][.{hotfix}][-{prerelease}][+{buildmetadata}]",
    "extra_info": False,
    "create_verinfo_files": False,
    "hide_zero_hotfix": True,
    "version_backends": {},
    "deps": {},
    "policies": {},
    "conventional_commits": {},
}

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

# Unused
__SEMVER_REGEX = (
    rf"^{_SEMVER_BASE_VER_REGEX}{_SEMVER_PRERELEASE_REGEX}{SEMVER_BUILDMETADATA_REGEX}$"
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


BOLD_CHAR = "\033[1m"
END_CHAR = "\033[0m"

RELATIVE_TO_CURRENT_VCS_POSITION_TYPE = "current"
RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE = "branch"
RELATIVE_TO_GLOBAL_TYPE = "global"

VMN_USER_NAME = "vmn"
VMN_BE_TYPE_GIT = "git"
VMN_BE_TYPE_LOCAL_FILE = "local_file"

GLOBAL_LOG_FILENAME = "global_vmn.log"
VMN_LOGGER = None


def comment_out_jinja(text: str) -> str:
    """
    Wrap every live tag so it survives rendering, e.g.
        {{ foo }}  →  {% raw %}{{ foo }}{% endraw %}
    """
    return JINJA_TAG_RE.sub(lambda m: '{% raw %}' + m.group(1) + '{% endraw %}', text)


# Create a custom execute function
def custom_execute(self, *args, **kwargs):
    global VMN_LOGGER

    if VMN_LOGGER is not None:
        VMN_LOGGER.debug(
            f"{BOLD_CHAR}{'  ' * (len(call_stack) - 1)}{' '.join(str(v) for v in args[0])}{END_CHAR}"
        )

    original_execute = getattr(self.__class__, "_execute")
    originally_extended_output = "with_extended_output" in kwargs
    kwargs["with_extended_output"] = True

    start_time = time.perf_counter()
    ret = original_execute(self, *args, **kwargs)
    end_time = time.perf_counter()

    ret_code = 0
    sout = ""
    serr = ""
    if not originally_extended_output:
        if type(ret) is tuple:
            ret_code = ret[0]
            sout = ret[1]
            serr = ret[2]
            ret = sout
    elif type(ret) is not tuple:
        sout = ret.stdout.read()
        serr = ret.stdout.read()
        ret_code = 0
        if serr:
            ret_code = 1

    time_took = end_time - start_time

    if VMN_LOGGER is not None:
        VMN_LOGGER.debug(
            f"{'  ' * (len(call_stack) - 1)}return code: {ret_code}, git cmd took: {time_took:.6f} seconds.\n"
            f"{'  ' * (len(call_stack) - 1)}stdout: {sout}\n"
            f"{'  ' * (len(call_stack) - 1)}stderr: {serr}"
        )

    return ret


# Monkey-patch the Git class
git.cmd.Git._execute = git.cmd.Git.execute
git.cmd.Git.execute = custom_execute

# Maintain a stack to keep track of nested function calls
call_stack = []
call_count = {}


def measure_runtime_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global call_stack
        global VMN_LOGGER

        if func.__name__ not in call_count:
            call_count[func.__name__] = 0
        call_count[func.__name__] += 1

        call_stack.append(func.__name__)
        fcode = func.__code__

        if VMN_LOGGER is not None:
            VMN_LOGGER.debug(
                f"{'  ' * (len(call_stack) - 1)}--> Entering {func.__name__} at {fcode.co_filename}:{fcode.co_firstlineno}"
            )

        start_time = time.perf_counter()
        # Call the actual function
        result = func(*args, **kwargs)
        end_time = time.perf_counter()

        elapsed_time = end_time - start_time

        if VMN_LOGGER is not None:
            VMN_LOGGER.debug(
                f"{'  ' * (len(call_stack) - 1)}<-- Exiting {func.__name__} {BOLD_CHAR} took {elapsed_time:.6f} seconds {END_CHAR} at {fcode.co_filename}:{fcode.co_firstlineno}"
            )

        call_stack.pop()

        return result

    return wrapper


class WrongTagFormatException(Exception):
    pass


def resolve_root_path():
    cwd = os.getcwd()
    if "VMN_WORKING_DIR" in os.environ:
        cwd = os.environ["VMN_WORKING_DIR"]

    root_path = os.path.realpath(os.path.expanduser(cwd))
    """
            ".git" is the default app's backend in this case. If other backends will be added, 
            then it can be moved to the configuration file as a default_backend or similar. 
        """
    exist = os.path.exists(os.path.join(root_path, ".git"))
    exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
    while not exist:
        try:
            prev_path = root_path
            root_path = os.path.realpath(os.path.join(root_path, ".."))
            if prev_path == root_path:
                raise RuntimeError()

            exist = os.path.exists(os.path.join(root_path, ".git"))
            exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            root_path = None
            break
    if root_path is None:
        raise RuntimeError("Running from an unmanaged directory")

    return root_path


class LevelFilter(logging.Filter):
    def __init__(self, low, high):
        self._low = low
        self._high = high
        logging.Filter.__init__(self)

    def filter(self, record):
        if self._low <= record.levelno <= self._high:
            return True
        return False


def init_stamp_logger(rotating_log_path=None, debug=False, supress_stdout=False):
    global VMN_LOGGER

    VMN_LOGGER = logging.getLogger(VMN_USER_NAME)
    clear_logger_handlers(VMN_LOGGER)
    glob_logger = logging.getLogger()
    clear_logger_handlers(glob_logger)

    glob_logger.setLevel(logging.DEBUG)
    logging.getLogger("git").setLevel(logging.WARNING)

    fmt = "[%(levelname)s] %(message)s"
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    min_stdout_level = logging.INFO
    if debug:
        min_stdout_level = logging.DEBUG

    stdout_handler.addFilter(LevelFilter(min_stdout_level, logging.INFO))

    if not supress_stdout or debug:
        VMN_LOGGER.addHandler(stdout_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)
    VMN_LOGGER.addHandler(stderr_handler)

    if rotating_log_path is None:
        return

    rotating_file_handler = init_log_file_handler(rotating_log_path)
    VMN_LOGGER.addHandler(rotating_file_handler)

    global_log_path = os.path.join(
        os.path.dirname(rotating_log_path), GLOBAL_LOG_FILENAME
    )
    global_file_handler = init_log_file_handler(global_log_path)
    glob_logger.addHandler(global_file_handler)


def init_log_file_handler(rotating_log_path):
    rotating_file_handler = RotatingFileHandler(
        rotating_log_path,
        maxBytes=1024 * 1024 * 50,
        backupCount=1,
    )
    rotating_file_handler.setLevel(logging.DEBUG)
    fmt = "[%(levelname)s] %(asctime)s %(pathname)s:%(lineno)d =>\n%(message)s"
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")
    rotating_file_handler.setFormatter(formatter)
    return rotating_file_handler


def clear_logger_handlers(logger_obj):
    hlen = len(logger_obj.handlers)
    for h in range(hlen):
        logger_obj.handlers[0].close()
        logger_obj.removeHandler(logger_obj.handlers[0])
    flen = len(logger_obj.filters)
    for f in range(flen):
        logger_obj.removeFilter(logger_obj.filters[0])


class VMNBackend(object):
    def __init__(self, btype):
        self._type = btype

    def __del__(self):
        pass

    def type(self):
        return self._type

    def prepare_for_remote_operation(self):
        return 0

    def get_active_branch(self):
        return "none"

    def remote(self):
        return "none"

    def get_last_user_changeset(self, version_files_to_track_diff, name):
        return "none"

    def get_actual_deps_state(self, vmn_root_path, paths):
        raise NotImplementedError()

    @staticmethod
    def app_name_to_tag_name(app_name):
        return app_name.replace("/", "-")

    @staticmethod
    def tag_name_to_app_name(tag_app_name):
        return tag_app_name.replace("-", "/")

    @staticmethod
    def gen_unique_id(verstr, hash):
        return f"{verstr}+{hash}"

    @staticmethod
    def get_utemplate_formatted_version(raw_vmn_version, template, hide_zero_hotfix):
        props = VMNBackend.deserialize_vmn_version(raw_vmn_version)

        if props["hotfix"] == 0 and hide_zero_hotfix:
            props["hotfix"] = None

        octats = (
            "major",
            "minor",
            "patch",
            "hotfix",
            "prerelease",
            "rcn",
            "buildmetadata",
        )

        formatted_version = ""
        for octat in octats:
            if props[octat] is None:
                continue

            if (
                f"{octat}_template" in template
                and template[f"{octat}_template"] is not None
            ):
                d = {octat: props[octat]}
                if "rcn" in d and props["old_ver_format"]:
                    continue

                if "prerelease" in d and d["prerelease"] == "release":
                    continue

                formatted_version = (
                    f"{formatted_version}"
                    f"{template[f'{octat}_template'].format(**d)}"
                )

        return formatted_version

    @staticmethod
    def get_root_app_name_from_name(name):
        root_app_name = name.split("/")
        if len(root_app_name) == 1:
            return None

        return "/".join(root_app_name[:-1])

    @staticmethod
    def serialize_vmn_tag_name(
        app_name,
        verstr,
    ):
        tag_app_name = VMNBackend.app_name_to_tag_name(app_name)
        tag_name = f"{tag_app_name}_{verstr}"

        try:
            props = VMNBackend.deserialize_tag_name(tag_name)
            if props["hotfix"] == 0:
                # tags are always without zero hotfix
                verstr = VMNBackend.serialize_vmn_version(verstr, hide_zero_hotfix=True)
                tag_name = f"{tag_app_name}_{verstr}"
                props = VMNBackend.deserialize_tag_name(tag_name)
        except Exception:
            err = f"Tag {tag_name} doesn't comply with: " f"{VMN_TAG_REGEX} format"
            VMN_LOGGER.error(err)

            raise RuntimeError(err)

        return tag_name

    @staticmethod
    def serialize_vmn_version(
        base_verstr,
        prerelease=None,
        rcn=None,
        buildmetadata=None,
        hide_zero_hotfix=False,
    ):
        props = VMNBackend.deserialize_vmn_version(base_verstr)
        base_verstr = VMNBackend.serialize_vmn_base_version(
            props["major"],
            props["minor"],
            props["patch"],
            props["hotfix"],
            hide_zero_hotfix=hide_zero_hotfix,
        )

        vmn_version = base_verstr

        if props["prerelease"] != "release":
            if prerelease is not None:
                VMN_LOGGER.warning(
                    "Tried to serialize verstr containing "
                    "prerelease component but also tried to append"
                    " another prerelease component. Will ignore it"
                )

            prerelease = props["prerelease"]
            if not props["old_ver_format"]:
                rcn = props["rcn"]

        if props["buildmetadata"] is not None:
            if prerelease is not None:
                VMN_LOGGER.warning(
                    "Tried to serialize verstr containing "
                    "buildmetadata component but also tried to append"
                    " another buildmetadata component. Will ignore it"
                )

            buildmetadata = props["buildmetadata"]

        if prerelease is not None:
            vmn_version = f"{vmn_version}-{prerelease}"

            if rcn is not None:
                vmn_version = f"{vmn_version}.{rcn}"

        if buildmetadata is not None:
            vmn_version = f"{vmn_version}+{buildmetadata}"

        return vmn_version

    @staticmethod
    def serialize_vmn_base_version(
        major, minor, patch, hotfix=None, hide_zero_hotfix=None
    ):
        if hide_zero_hotfix and hotfix == 0:
            hotfix = None

        vmn_version = f"{major}.{minor}.{patch}"
        if hotfix is not None:
            vmn_version = f"{vmn_version}.{hotfix}"

        return vmn_version

    @staticmethod
    def get_base_vmn_version(some_verstr, hide_zero_hotfix=None):
        props = VMNBackend.deserialize_vmn_version(some_verstr)

        vmn_version = VMNBackend.serialize_vmn_base_version(
            props["major"],
            props["minor"],
            props["patch"],
            props["hotfix"],
            hide_zero_hotfix,
        )

        return vmn_version

    @staticmethod
    def deserialize_tag_name(some_tag):
        ret = {
            "app_name": None,
            "old_tag_format": False,
        }

        match = re.search(VMN_ROOT_TAG_REGEX, some_tag)
        if match is not None:
            gdict = match.groupdict()
            ret["app_name"] = gdict["app_name"]
        else:
            match = re.search(VMN_TAG_REGEX, some_tag)
            old_tag_format = False
            if match is None:
                match = re.search(VMN_OLD_TAG_REGEX, some_tag)
                if match is None:
                    raise WrongTagFormatException()

                old_tag_format = True

            gdict = match.groupdict()
            if old_tag_format:
                ret["old_tag_format"] = True

            ret["app_name"] = VMNBackend.tag_name_to_app_name(gdict["app_name"])

        res = VMNBackend.app_name_to_tag_name(ret["app_name"])
        ret["verstr"] = some_tag.split(f"{res}_")[1]

        ret.update(VMNBackend.deserialize_vmn_version(ret["verstr"]))

        return ret

    @staticmethod
    def deserialize_vmn_version(verstr):
        ret = {
            "types": {"version"},
            "root_version": None,
            "major": None,
            "minor": None,
            "patch": None,
            "hotfix": None,
            "prerelease": "release",
            "rcn": None,
            "buildmetadata": None,
            "old_ver_format": False,
        }

        match = re.search(VMN_ROOT_VERSION_REGEX, verstr)
        if match is not None:
            gdict = match.groupdict()

            int(gdict["version"])
            ret["root_version"] = gdict["version"]
            ret["types"].add("root")

            return ret

        match = re.search(VMN_VERSION_REGEX, verstr)
        old_ver_format = False
        if match is None:
            match = re.search(VMN_OLD_REGEX, verstr)
            if match is None:
                raise WrongTagFormatException()

            old_ver_format = True

        gdict = match.groupdict()
        if old_ver_format:
            gdict["rcn"] = -1
            ret["old_ver_format"] = True

        ret["major"] = int(gdict["major"])
        ret["minor"] = int(gdict["minor"])
        ret["patch"] = int(gdict["patch"])
        ret["hotfix"] = 0

        if gdict["hotfix"] is not None:
            ret["hotfix"] = int(gdict["hotfix"])

        if gdict["prerelease"] is not None:
            ret["prerelease"] = gdict["prerelease"]
            ret["rcn"] = int(gdict["rcn"])
            ret["types"].add("prerelease")

        if gdict["buildmetadata"] is not None:
            ret["buildmetadata"] = gdict["buildmetadata"]
            ret["types"].add("buildmetadata")

        return ret

    @staticmethod
    def deserialize_vmn_tag_name(vmn_tag):
        try:
            return VMNBackend.deserialize_tag_name(vmn_tag)
        except WrongTagFormatException as exc:
            VMN_LOGGER.error(
                f"Tag {vmn_tag} doesn't comply to vmn version format",
                exc_info=True,
            )

            raise exc
        except Exception as exc:
            VMN_LOGGER.error(
                f"Failed to deserialize tag {vmn_tag}",
                exc_info=True,
            )

            raise exc


class LocalFileBackend(VMNBackend):
    def __init__(self, repo_path):
        VMNBackend.__init__(self, VMN_BE_TYPE_LOCAL_FILE)

        vmn_dir_path = os.path.join(repo_path, ".vmn")
        if not os.path.isdir(vmn_dir_path):
            raise RuntimeError(
                "LocalFile backend needs to be initialized with a local"
                " path containing .vmn dir in it"
            )

        self.repo_path = repo_path
        self.active_branch = "none"
        self.remote_active_branch = "remote/none"

    def __del__(self):
        pass

    def perform_cached_fetch(self, force=False):
        return

    def get_first_reachable_version_info(
        self, app_name, root=False, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        ver_infos = {
            "none": {
                "tag_object": None,
                "commit_obj": None,
                "ver_info": None,
            }
        }
        if root:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
            list_of_files = glob.glob(os.path.join(dir_path, "*.yml"))
            if not list_of_files:
                return None, {}

            latest_file = max(list_of_files, key=os.path.getctime)
            with open(latest_file, "r") as f:
                ver_infos["none"]["ver_info"] = yaml.safe_load(f)
                return "none", ver_infos

        dir_path = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")
        list_of_files = glob.glob(os.path.join(dir_path, "*.yml"))
        if not list_of_files:
            return None, {}

        latest_file = max(list_of_files, key=os.path.getctime)

        with open(latest_file, "r") as f:
            ver_infos["none"]["ver_info"] = yaml.safe_load(f)
            return "none", ver_infos

    def get_latest_available_tag(self, tag_prefix_filter):
        return None

    def get_actual_deps_state(self, vmn_root_path, paths):
        actual_deps_state = {
            ".": {
                "hash": "0xdeadbeef",
                "remote": "none",
                "vcs_type": VMN_BE_TYPE_LOCAL_FILE,
            }
        }

        return actual_deps_state

    def get_tag_version_info(self, tag_name):
        tagd = VMNBackend.deserialize_vmn_tag_name(tag_name)
        if "root" in tagd["types"]:
            dir_path = os.path.join(
                self.repo_path, ".vmn", tagd["app_name"], "root_verinfo"
            )
            path = os.path.join(dir_path, f"{tagd['root_version']}.yml")
        else:
            dir_path = os.path.join(self.repo_path, ".vmn", tagd["app_name"], "verinfo")
            path = os.path.join(dir_path, f"{tagd['verstr']}.yml")

        ver_infos = {}
        try:
            with open(path, "r") as f:
                ver_infos = {
                    tag_name: {
                        "ver_info": None,
                        "tag_object": None,
                        "commit_object": None,
                    }
                }
                ver_infos[tag_name]["ver_info"] = yaml.safe_load(f)
        except Exception:
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

        return tag_name, ver_infos

    @measure_runtime_decorator
    def get_latest_stamp_tags(
        self, app_name, root_context, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        if root_context:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "root_verinfo")
        else:
            dir_path = os.path.join(self.repo_path, ".vmn", app_name, "verinfo")

        files = glob.glob(os.path.join(dir_path, "*"))

        # sort the files by modification date
        files.sort(key=os.path.getmtime, reverse=True)

        ver_infos = {}
        tag_names = []
        if files:
            with open(files[0], "r") as f:
                data = yaml.safe_load(f)
                if root_context:
                    ver = data["stamping"]["root_app"]["version"]
                else:
                    ver = data["stamping"]["app"]["_version"]

                tag_name = VMNBackend.serialize_vmn_tag_name(app_name, ver)
                tag_names.append(tag_name)
                ver_infos = {
                    tag_name: {
                        "ver_info": None,
                        "tag_object": None,
                        "commit_object": None,
                    }
                }
                ver_infos[tag_name]["ver_info"] = data

        return tag_names, None, ver_infos


class GitBackend(VMNBackend):
    @measure_runtime_decorator
    def __init__(self, repo_path, inherit_env=False):
        VMNBackend.__init__(self, VMN_BE_TYPE_GIT)

        self._be = GitBackend.initialize_git_backend(repo_path, inherit_env)
        self.add_git_user_cfg_if_missing()

        # TODO:: make selected_remote configurable.
        # Currently just selecting the first one
        self.selected_remote = self._be.remotes[0]
        self.repo_path = repo_path
        self.active_branch = self.get_active_branch()
        self.remote_active_branch = self.get_remote_tracking_branch(self.active_branch)
        self.detached_head = self.in_detached_head()

    @measure_runtime_decorator
    def perform_cached_fetch(self, force=False):
        vmn_cache_path = os.path.join(self.repo_path, ".vmn", "vmn.cache")
        if not os.path.exists(vmn_cache_path) or force:
            pathlib.Path(os.path.join(self.repo_path, ".vmn")).mkdir(
                parents=True, exist_ok=True
            )
            pathlib.Path(vmn_cache_path).touch()

            self._be.git.execute(["git", "fetch", "--tags"])
        elif os.path.exists(vmn_cache_path):
            minutes_ago = datetime.datetime.now() - datetime.timedelta(minutes=30)
            filemtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(vmn_cache_path)
            )
            # file is more than 30 minutes old
            if filemtime < minutes_ago:
                pathlib.Path(vmn_cache_path).touch()
                self._be.git.execute(["git", "fetch", "--tags"])

    def __del__(self):
        self._be.close()

    @staticmethod
    @measure_runtime_decorator
    def initialize_git_backend(repo_path, inherit_env):
        be = git.Repo(repo_path, search_parent_directories=True)

        if inherit_env:
            current_git_env = {
                k: os.environ[k] for k in os.environ if k.startswith("GIT_")
            }
            current_git_env.update(
                {
                    "GIT_AUTHOR_NAME": VMN_USER_NAME,
                    "GIT_COMMITTER_NAME": VMN_USER_NAME,
                    "GIT_AUTHOR_EMAIL": VMN_USER_NAME,
                    "GIT_COMMITTER_EMAIL": VMN_USER_NAME,
                }
            )
            be.git.update_environment(**current_git_env)

        return be

    @staticmethod
    @measure_runtime_decorator
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        except Exception:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remotes[0].urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception:
            VMN_LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        finally:
            client.close()

        return hash, remote, "git"

    @measure_runtime_decorator
    def is_path_tracked(self, path):
        try:
            self._be.git.execute(["git", "ls-files", "--error-unmatch", path])
            return True
        except Exception:
            VMN_LOGGER.debug(f"Logged exception for path {path}: ", exc_info=True)
            return False

    @measure_runtime_decorator
    def tag(self, tags, messages, ref="HEAD", push=False):
        if push and self.remote_active_branch is None:
            raise RuntimeError("Will not push remote branch does not exist")

        for tag, message in zip(tags, messages):
            # This is required in order to preserver chronological order when
            # listing tags since the taggerdate field is in seconds resolution
            time.sleep(1.1)

            self._be.create_tag(tag, ref=ref, message=message)

            if not push:
                continue

            try:
                self._be.git.execute(
                    [
                        "git",
                        "push",
                        "--porcelain",
                        "-o",
                        "ci.skip",
                        self.selected_remote.name,
                        f"refs/tags/{tag}",
                    ]
                )
            except Exception:
                try:
                    self._be.git.execute(
                        [
                            "git",
                            "push",
                            "--porcelain",
                            self.selected_remote.name,
                            f"refs/tags/{tag}",
                        ]
                    )
                except Exception:
                    tag_err_str = f"Failed to tag {tag}. Reverting.."
                    VMN_LOGGER.error(tag_err_str)

                    try:
                        self._be.delete_tag(tag)
                    except Exception:
                        err_str = f"Failed to remove tag {tag}"
                        VMN_LOGGER.info(err_str)
                        VMN_LOGGER.debug("Exception info: ", exc_info=True)

                    raise RuntimeError(tag_err_str)

    @measure_runtime_decorator
    def push(self, tags=(), branch=None, atomic=False):
        if self.detached_head:
            raise RuntimeError("Will not push from detached head")

        if self.remote_active_branch is None:
            raise RuntimeError("Will not push remote branch does not exist")

        remote_branch_name_no_remote_name = branch
        if remote_branch_name_no_remote_name is None:
            remote_branch_name_no_remote_name = "".join(
                self.remote_active_branch.split(f"{self.selected_remote.name}/")
            )

        def _push_once(ci_skip=True, do_branch=True, do_tags=(), use_atomic=False):
            cmd = ["git", "push", "--porcelain"]
            if ci_skip:
                cmd += ["-o", "ci.skip"]
            if use_atomic:
                cmd.append("--atomic")
            cmd.append(self.selected_remote.name)
            if do_branch:
                cmd.append(
                    f"refs/heads/{self.active_branch}:{remote_branch_name_no_remote_name}"
                )
            for t in do_tags:
                cmd.append(f"refs/tags/{t}")
            self._be.git.execute(cmd)

        if atomic:
            try:
                _push_once(True, True, tags, True)
            except Exception:
                try:
                    _push_once(False, True, tags, True)
                except Exception:
                    err_str = "Push has failed. Please verify that 'git push' works"
                    VMN_LOGGER.error(err_str, exc_info=True)
                    raise RuntimeError(err_str)
        else:
            try:
                _push_once(True, True)
            except Exception:
                _push_once(False, True)

        for tag in tags:
            try:
                _push_once(True, False, [tag])
            except Exception:
                _push_once(False, False, [tag])


    @measure_runtime_decorator
    def pull(self):
        if self.detached_head:
            raise RuntimeError("Will not pull in detached head")

        self.selected_remote.pull("--ff-only")

    @measure_runtime_decorator
    def commit(self, message, user, include=None):
        if include is not None:
            for file in include:
                self._be.index.add(file)
        author = git.Actor(user, user)

        self._be.index.commit(message=message, author=author)

    @measure_runtime_decorator
    def root(self):
        return self._be.working_dir

    @measure_runtime_decorator
    def status(self, tag):
        found_tag = self._be.tag(f"refs/tags/{tag}")
        try:
            return tuple(found_tag.commit.stats.files)
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            return None

    @measure_runtime_decorator
    def get_latest_stamp_tags(
        self, app_name, root_context, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        if root_context:
            msg_filter = f"^{app_name}/.*: Stamped"
        else:
            msg_filter = f"^{app_name}: Stamped"

        if type == RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE:
            cmd_suffix = f"refs/heads/{self.active_branch}"
        elif type == RELATIVE_TO_CURRENT_VCS_POSITION_TYPE:
            cmd_suffix = "HEAD"
        else:
            cmd_suffix = "--branches"

        shallow = os.path.exists(os.path.join(self._be.common_dir, "shallow"))
        if shallow:
            # This is the only usecase where we must perform a remote operation
            # because otherwise even show will not work
            self.perform_cached_fetch()
            (
                tag_names,
                cobj,
                ver_infos,
            ) = self._get_shallow_first_reachable_vmn_stamp_tag_list(
                app_name,
                cmd_suffix,
                msg_filter,
            )
        else:
            tag_names, cobj, ver_infos = self._get_first_reachable_vmn_stamp_tag_list(
                app_name, cmd_suffix, msg_filter
            )

        return tag_names, cobj, ver_infos

    @measure_runtime_decorator
    def _get_first_reachable_vmn_stamp_tag_list(self, app_name, cmd_suffix, msg_filter):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)
        bug_limit = 1000
        bug_limit_c = 0
        while not ver_infos and bug_limit_c < bug_limit:
            if cobj is None:
                break

            cmd_suffix = f"{cobj.hexsha}~1"
            cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

            bug_limit += 1
            if bug_limit_c == bug_limit:
                VMN_LOGGER.warning(
                    "Probable bug: vmn failed to find "
                    f"vmn's commit after {bug_limit} interations."
                )
                ver_infos = {}
                break

        tag_objects = []
        for k in ver_infos:
            tag_objects.append(ver_infos[k]["tag_object"])

        # We want the newest tag on top because we skip "buildmetadata tags"
        tag_objects = sorted(
            tag_objects, key=lambda t: t.object.tagged_date, reverse=True
        )
        tag_names = []
        for tag_object in tag_objects:
            tag_names.append(tag_object.name)

        return tag_names, cobj, ver_infos

    @measure_runtime_decorator
    def _get_shallow_first_reachable_vmn_stamp_tag_list(
        self, app_name, cmd_suffix, msg_filter
    ):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

        if ver_infos:
            tag_objects = []
            for k in ver_infos:
                tag_objects.append(ver_infos[k]["tag_object"])

            # We want the newest tag on top because we skip "buildmetadata tags"
            tag_objects = sorted(
                tag_objects, key=lambda t: t.object.tagged_date, reverse=True
            )
            tag_names = []
            for tag_object in tag_objects:
                tag_names.append(tag_object.name)

            return tag_names, cobj, ver_infos

        tag_name_prefix = VMNBackend.app_name_to_tag_name(app_name)
        cmd = ["--sort", "taggerdate", "--list", f"{tag_name_prefix}_*"]
        tag_names = self._be.git.tag(*cmd).split("\n")

        if len(tag_names) == 1 and tag_names[0] == "":
            tag_names.pop(0)

        if not tag_names:
            return tag_names, cobj, ver_infos

        latest_tag = tag_names[-1]
        head_date = self._be.head.commit.committed_date
        for tname in reversed(tag_names):
            tname, o = self.get_tag_object_from_tag_name(tname)
            if o:
                if (
                    self._be.head.commit.hexsha != o.commit.hexsha
                    and head_date < o.object.tagged_date
                ):
                    continue

                latest_tag = tname
                break

        try:
            found_tag = self._be.tag(f"refs/tags/{latest_tag}")
        except Exception:
            VMN_LOGGER.error(f"Failed to get tag object from tag name: {latest_tag}")
            return [], cobj, ver_infos

        ver_infos = self.get_all_commit_tags(found_tag.commit.hexsha)
        tag_objects = []

        for k in ver_infos.keys():
            if ver_infos[k]["tag_object"]:
                tag_objects.append(ver_infos[k]["tag_object"])

        # We want the newest tag on top because we skip "buildmetadata tags"
        tag_objects = sorted(
            tag_objects, key=lambda t: t.object.tagged_date, reverse=True
        )

        final_list_of_tag_names = []
        for tag_object in tag_objects:
            final_list_of_tag_names.append(tag_object.name)

        return final_list_of_tag_names, found_tag.commit, ver_infos

    @measure_runtime_decorator
    def _get_top_vmn_commit(self, app_name, cmd_suffix, msg_filter):
        cmd = [
            f"--grep={msg_filter}",
            "-1",
            f"--author={VMN_USER_NAME}",
            "--pretty=%H,,,%D",
            "--decorate=short",
            cmd_suffix,
        ]
        log_res = self._be.git.log(*cmd).split("\n")
        if len(log_res) == 1 and log_res[0] == "":
            log_res.pop(0)

        if not log_res:
            return None, {}

        items = log_res[0].split(",,,")
        tags = items[1].split(",")
        if len(tags) == 1 and tags[0] == "":
            tags.pop(0)

        commit_hex = items[0]
        ver_infos = self.get_all_commit_tags_log_impl(commit_hex, tags, app_name)

        cobj = self.get_commit_object_from_commit_hex(commit_hex)

        return cobj, ver_infos

    @measure_runtime_decorator
    def get_latest_available_tags(self, tag_prefix_filter):
        cmd = ["--sort", "taggerdate", "--list", tag_prefix_filter]
        tag_names = self._be.git.tag(*cmd).split("\n")

        if len(tag_names) == 1 and tag_names[0] == "":
            return None

        return tag_names

    @measure_runtime_decorator
    def get_latest_available_tag(self, tag_prefix_filter):
        tnames = self.get_latest_available_tags(tag_prefix_filter)
        if tnames is None:
            return None

        return tnames[-1]

    @measure_runtime_decorator
    def get_commit_object_from_branch_name(self, bname):
        # TODO:: Unfortunately, need to spend o(N) here
        for branch in self._be.branches:
            if bname != branch.name:
                continue

            # yay, we found the tag's commit object
            return branch.commit

        raise RuntimeError(
            f"Somehow did not find a branch commit object for branch: {bname}"
        )

    @measure_runtime_decorator
    def get_tag_object_from_tag_name(self, tname):
        try:
            o = self._be.tag(f"refs/tags/{tname}")
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            # Backward compatability code for vmn 0.3.9:
            try:
                _tag_name = f"{tname}.0"
                o = self._be.tag(f"refs/tags/{tname}")
            except Exception:
                VMN_LOGGER.debug("Logged exception: ", exc_info=True)
                return tname, None

        try:
            if o.commit.author.name != "vmn":
                return tname, None
        except Exception:
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            return tname, None

        if o.tag is None:
            return tname, None

        if o is None:
            VMN_LOGGER.debug(f"Somehow did not find a tag object for tag: {tname}")

        return tname, o

    @measure_runtime_decorator
    def get_all_commit_tags_log_impl(self, hexsha, tags, app_name):
        cleaned_tags = []
        for t in tags:
            if "tag:" not in t:
                continue

            tname = t.split("tag:")[1].strip()
            cleaned_tags.append(tname)

        ver_infos = {}
        if not cleaned_tags:
            # Maybe rebase or tag was removed. Will handle the rebase case here
            try:
                commit_obj = self.get_commit_object_from_commit_hex(hexsha)
                verstr = commit_obj.message.split(" version ")[1].strip()
                tagname = f"{app_name}_{verstr}"
                tagname, ver_info_c = self.parse_tag_message(tagname)
                if ver_info_c["tag_object"]:
                    ver_infos[tagname] = ver_info_c

                    cleaned_tags = self.get_all_brother_tags(tagname)
                    cleaned_tags.pop(tagname)
                    cleaned_tags = cleaned_tags.keys()
            except Exception:
                VMN_LOGGER.debug(f"Skipped on {hexsha} commit")

        for tname in cleaned_tags:
            tname, ver_info_c = self.parse_tag_message(tname)
            if ver_info_c["ver_info"] is None:
                VMN_LOGGER.debug(
                    f"Probably non-vmn tag - {tname} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[tname] = ver_info_c

        return ver_infos

    @measure_runtime_decorator
    def get_all_commit_tags(self, hexsha="HEAD"):
        if hexsha is None:
            hexsha = "HEAD"

        cmd = ["--points-at", hexsha]
        tags = self._be.git.tag(*cmd).split("\n")

        if len(tags) == 1 and tags[0] == "":
            tags.pop(0)

        ver_infos = {}
        for t in tags:
            t, ver_info_c = self.parse_tag_message(t)
            if ver_info_c["ver_info"] is None:
                VMN_LOGGER.debug(
                    f"Probably non-vmn tag - {t} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[t] = ver_info_c

        return ver_infos

    @measure_runtime_decorator
    def get_all_brother_tags(self, tag_name):
        try:
            sha = self.changeset(tag=tag_name)
            ver_infos = self.get_all_commit_tags(sha)
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to get brother tags for tag: {tag_name}. "
                f"Logged exception: ",
                exc_info=True,
            )
            return []

        return ver_infos

    def in_detached_head(self):
        return self._be.head.is_detached

    @measure_runtime_decorator
    def add_git_user_cfg_if_missing(self):
        try:
            self._be.config_reader().get_value("user", "name")
            self._be.config_reader().get_value("user", "email")
        except (configparser.NoSectionError, configparser.NoOptionError):
            # git user name or email configuration is missing, add default override
            self._be.git.set_persistent_git_options(
                c=[f'user.name="{VMN_USER_NAME}"', f'user.email="{VMN_USER_NAME}"']
            )

    @measure_runtime_decorator
    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = f"Pending changes in {self.root()}."
            return err

        return None

    @measure_runtime_decorator
    def check_for_outgoing_changes(self):
        if self.in_detached_head():
            err = f"Detached head in {self.root()}."
            return err

        if self.remote_active_branch is None:
            err = (
                f"No upstream branch found in {self.root()}. "
                f"for local branch {self.active_branch}. "
                f"Probably no upstream branch is set"
            )

            return err

        branch_name = self.active_branch
        try:
            self._be.git.rev_parse("--verify", f"{self.remote_active_branch}")
        except Exception:
            err = (
                f"Remote branch {self.remote_active_branch} does not exist. "
                "Please set-upstream branch to "
                f"{self.remote_active_branch} of branch {branch_name}"
            )
            return err

        outgoing = tuple(
            self._be.iter_commits(f"{self.remote_active_branch}..{branch_name}")
        )

        if len(outgoing) > 0:
            err = (
                f"Outgoing changes in {self.root()} "
                f"from branch {branch_name} "
                f"({self.remote_active_branch}..{branch_name})\n"
                f"The commits that are outgoing are: {outgoing}"
            )

            return err

        return None

    @measure_runtime_decorator
    def checkout_branch(self, branch_name=None):
        try:
            if branch_name is None:
                branch_name = self.active_branch

            self.checkout(branch=branch_name)
        except Exception:
            logging.error("Failed to get branch name")
            VMN_LOGGER.debug("Exception info: ", exc_info=True)

            return None

        return self._be.active_branch.commit.hexsha

    @measure_runtime_decorator
    def get_remote_tracking_branch(self, local_branch_name):
        command = [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{local_branch_name}@{{u}}",
        ]

        try:
            ret = self._be.git.execute(command)

            try:
                assert ret.startswith(self.selected_remote.name)
            except Exception:
                VMN_LOGGER.warning(
                    f"Found remote branch {ret} however it belongs to a "
                    f"different remote that vmn has selected to work with. "
                    f"Will behave like no remote was found. The remote that vmn has "
                    f"selected to work with is: {self.selected_remote.name}"
                )

                return None

            return ret
        except Exception:
            return None

    @measure_runtime_decorator
    def prepare_for_remote_operation(self):
        if self.remote_active_branch is not None:
            return 0

        local_branch_name = self.active_branch

        VMN_LOGGER.warning(
            f"No remote branch for local branch: {local_branch_name} "
            f"was found for repo {self.repo_path}. Will try to set upstream for it"
        )

        assumed_remote = f"{self.selected_remote.name}/{local_branch_name}"

        out = self._be.git.branch("-r", "--contains", "HEAD")
        out = [s.strip() for s in out.split("\n")]

        VMN_LOGGER.info(f"The output of 'git branch -r --contains HEAD' is:\n{out}")

        if assumed_remote in out:
            VMN_LOGGER.info(
                f"Assuming remote: {assumed_remote} as it was present in the output"
            )
            out = assumed_remote
        elif out:
            VMN_LOGGER.info(
                f"Assuming remote: {out[0]} as this is the first element in the output"
            )
            out = out[0]

        if not out:
            VMN_LOGGER.info(
                f"Assuming remote: {assumed_remote} as the output was empty"
            )
            out = assumed_remote

        try:
            self._be.git.execute(
                [
                    "git",
                    "remote",
                    "set-branches",
                    "--add",
                    self.selected_remote.name,
                    local_branch_name,
                ]
            )
            self._be.git.branch(f"--set-upstream-to={out}", local_branch_name)
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to set upstream branch for {local_branch_name}:", exc_info=True
            )
            return 1

        self.remote_active_branch = out

        return 0

    @measure_runtime_decorator
    def get_active_branch(self):
        # TODO:: return the full ref name: refs/heads/..
        if not self.in_detached_head():
            active_branch = self._be.active_branch.name
        else:
            active_branch = self.get_branch_from_changeset(self._be.head.commit.hexsha)

        return active_branch

    @measure_runtime_decorator
    def get_branch_from_changeset(self, hexsha):
        out = self._be.git.branch("--contains", hexsha)

        branches = out.splitlines()

        # Clean up each branch name by stripping whitespace and the '*' character
        active_branches = []
        for branch in branches:
            cleaned_branch = branch.strip().lstrip("*").strip()
            if "HEAD detached" not in cleaned_branch:
                active_branches.append(cleaned_branch)

        if len(active_branches) > 1:
            VMN_LOGGER.info(
                f"{self._be.head.commit.hexsha} is "
                f"related to multiple branches: {active_branches}. "
                "Using the first one as the active branch"
            )

        if not active_branches:
            out = self._be.git.branch("-r", "--contains", hexsha)
            out = out.split("\n")[0].strip()

            if not out:
                raise RuntimeError(f"Failed to find remote branch for hex: {hexsha}")

            assert out.startswith(self.selected_remote.name)

            local_branch_name = (
                f"vmn_tracking_remote__{out.replace('/', '_')}__from_{hexsha[:5]}"
            )
            self._be.git.branch(local_branch_name, out)
            self._be.git.branch(f"--set-upstream-to={out}", local_branch_name)

            VMN_LOGGER.debug(
                f"Setting local branch {local_branch_name} "
                f"to track remote branch {out}"
            )

            self.active_branch = local_branch_name
            self.remote_active_branch = out

            remote_branch_hexsha = self._be.refs[out].commit.hexsha
            if remote_branch_hexsha == hexsha:
                ret = self.checkout_branch()
                assert ret is not None

            active_branches.append(local_branch_name)

        active_branch = active_branches[0]

        return active_branch

    @measure_runtime_decorator
    def checkout(self, rev=None, tag=None, branch=None):
        if tag is not None:
            rev = f"refs/tags/{tag}"
        elif branch is not None:
            # TODO:: f"refs/heads/{branch}"
            rev = f"{branch}"

        assert rev is not None

        self._be.git.checkout(rev)

        self.detached_head = self.in_detached_head()

    @measure_runtime_decorator
    def get_actual_deps_state(self, vmn_root_path, paths):
        actual_deps_state = {}
        for path in paths:
            full_path = os.path.join(vmn_root_path, path)
            details = GitBackend.get_repo_details(full_path)
            if details is None:
                continue

            actual_deps_state[path] = {
                "hash": details[0],
                "remote": details[1],
                "vcs_type": details[2],
            }

        return actual_deps_state

    @measure_runtime_decorator
    def get_last_user_changeset(self, version_files_to_track_diff_off, name):
        p = self._be.head.commit
        if p.author.name != VMN_USER_NAME:
            return p.hexsha

        if p.message.startswith(INIT_COMMIT_MESSAGE):
            return p.hexsha

        # TODO:: think how to use this tags for later in order
        #  to avoid getting all tags again. Not sure this is a problem even
        ver_infos = self.get_all_commit_tags(p.hexsha)
        if not ver_infos:
            VMN_LOGGER.warning(
                f"Somehow vmn's commit {p.hexsha} has no tags. "
                f"Check your repo. Assuming this commit is a user commit"
            )
            return p.hexsha

        for t, v in ver_infos.items():
            if "stamping" in v["ver_info"]:
                prev_user_commit = v["ver_info"]["stamping"]["app"]["changesets"]["."]["hash"]

                ret_d, ret_list = self.parse_git_log_to_commit_for_specific_file(
                    prev_user_commit,
                    p.hexsha,
                    version_files_to_track_diff_off
                )

                # TODO:: think if we want to support cases where file changed
                #  multiple times but eventually it came to be the same
                if name in ret_d and len(ret_list) > 1 and ret_list[0][0] != name:
                    return ret_list[0][1]

                return prev_user_commit

        VMN_LOGGER.warning(
            f"Somehow vmn's commit {p.hexsha} has no tags that are parsable. "
            f"Check your repo. Assuming this commit is a user commit"
        )

        return p.hexsha

    @measure_runtime_decorator
    def remote(self):
        remote = tuple(self.selected_remote.urls)[0]

        if os.path.isdir(remote):
            remote = os.path.relpath(remote, self.root())

        return remote

    @measure_runtime_decorator
    def changeset(self, tag=None, short=False):
        if tag is None:
            if short:
                return self._be.head.commit.hexsha[:6]

            return self._be.head.commit.hexsha

        found_tag = self._be.tag(f"refs/tags/{tag}")

        try:
            if short:
                return found_tag.commit.hexsha[:6]

            return found_tag.commit.hexsha
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            return None

    @measure_runtime_decorator
    def revert_local_changes(self, files=[]):
        if files:
            try:
                try:
                    for f in files:
                        self._be.git.reset(f)
                except Exception:
                    VMN_LOGGER.debug(
                        f"Failed to git reset files: {files}", exc_info=True
                    )

                self._be.index.checkout(files, force=True)
            except Exception:
                VMN_LOGGER.debug(
                    f"Failed to git checkout files: {files}", exc_info=True
                )

    @measure_runtime_decorator
    def revert_vmn_commit(self, prev_changeset, version_files, tags=[]):
        self.revert_local_changes(version_files)

        # TODO: also validate that the commit is
        #  currently worked on app name
        if self.changeset() == prev_changeset:
            return

        if self._be.active_branch.commit.author.name != VMN_USER_NAME:
            VMN_LOGGER.error("BUG: Will not revert non-vmn commit.")
            raise RuntimeError()

        self._be.git.reset("--hard", "HEAD~1")
        for tag in tags:
            try:
                self._be.delete_tag(tag)
            except Exception:
                VMN_LOGGER.info(f"Failed to remove tag {tag}")
                VMN_LOGGER.debug("Exception info: ", exc_info=True)

                continue

        try:
            self._be.git.fetch("--tags")
        except Exception:
            VMN_LOGGER.info("Failed to fetch tags")
            VMN_LOGGER.debug("Exception info: ", exc_info=True)

    @measure_runtime_decorator
    def get_tag_version_info(self, tag_name):
        ver_infos = {}
        tag_name, commit_tag_obj = self.get_commit_object_from_tag_name(tag_name)

        if commit_tag_obj is None:
            VMN_LOGGER.debug(f"Tried to find {tag_name} but with no success")
            return tag_name, ver_infos

        if commit_tag_obj.author.name != VMN_USER_NAME:
            VMN_LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ver_infos

        # "raw" ver_infos
        ver_infos = self.get_all_brother_tags(tag_name)
        if tag_name not in ver_infos:
            VMN_LOGGER.debug(f"Could not find version info for {tag_name}")
            return tag_name, None

        return tag_name, ver_infos

    @measure_runtime_decorator
    def parse_tag_message(self, tag_name):
        tag_name, tag_obj = self.get_tag_object_from_tag_name(tag_name)

        ret = {"ver_info": None, "tag_object": tag_obj, "commit_object": None}
        if not tag_obj:
            return tag_name, ret

        commit_tag_obj = tag_obj.commit
        if commit_tag_obj is None or commit_tag_obj.author.name != VMN_USER_NAME:
            VMN_LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ret

        ret["commit_object"] = commit_tag_obj

        # TODO:: Check API commit version
        # safe_load discards any text before the YAML document (if present)
        ver_info = yaml.safe_load(tag_obj.object.message)
        if ver_info is None:
            return tag_name, ret

        if not isinstance(ver_info, dict) and ver_info.startswith("Automatic"):
            # Code from vmn 0.3.9
            # safe_load discards any text before the YAML document (if present)
            commit_msg = yaml.safe_load(self._be.commit(tag_name).message)

            if commit_msg is not None and "stamping" in commit_msg:
                commit_msg["stamping"]["app"]["prerelease"] = "release"
                commit_msg["stamping"]["app"]["prerelease_count"] = {}

            ver_info = commit_msg
            if ver_info is None:
                return tag_name, ret

        if "vmn_info" not in ver_info:
            VMN_LOGGER.debug(f"vmn_info key was not found in tag {tag_name}")
            return tag_name, ret

        ret["ver_info"] = ver_info

        return tag_name, ret

    @measure_runtime_decorator
    def get_commit_object_from_commit_hex(self, hex):
        return self._be.commit(hex)

    def parse_git_log_to_commit_for_specific_file(self, from_commit, to_commit, filenames):
        try:
            if not filenames:
                return {}, []

            # Define the log format and construct the git log command
            log_format = "--format=%H %s"
            git_log_command = [
                "log",
                "--ancestry-path",
                log_format,
                f"{from_commit}..{to_commit}",
                "--",
            ] + filenames

            # Run the git log command
            logs = self._be.git.execute(["git"] + git_log_command)

            # Parse the log output
            log_entries = logs.splitlines()
            result = set()
            result_list = []

            for entry in log_entries:
                # Use regex to extract commit hash and tag
                match = re.match(r"^(\w{40})\s+([\w_]+):", entry)
                if match:
                    hexsha = match.group(1)
                    tag = match.group(2)
                    result.add(tag)
                    result_list.append((tag, hexsha))

            return result, result_list

        except git.exc.GitCommandError as e:
            VMN_LOGGER.error(f"Git command failed: {e}")
            return {}, []
        except Exception as e:
            VMN_LOGGER.error(f"An error occurred when tried to parse log: {e}")
            return {}, []

    def get_commits_range_iter(self, tag_name, to_hex="HEAD"):
        # def _commit_exists_locally(self, commit_hash):
        #     """
        #     Check if the given commit exists locally.
        #     """
        #     try:
        #         subprocess.check_output(["git", "cat-file", "-e", commit_hash])
        #         return True
        #     except subprocess.CalledProcessError:
        #         return False

        from_hex = self._be.tags[tag_name].commit

        shallow = os.path.exists(os.path.join(self._be.common_dir, "shallow"))
        if shallow:
            self._be.git.execute(["git", "fetch", "--unshallow"])
            # if from_hex is not present because shallow,
            # fetch incrementally with deepen until commit found
            # self._be.git.execute(["git", "fetch", "--deepen", "1"])

        i = self._be.iter_commits(f"{from_hex}..{to_hex}")

        return CommitMessageIterator(i)

    @measure_runtime_decorator
    def get_commit_object_from_tag_name(self, tag_name):
        try:
            commit_tag_obj = self._be.commit(tag_name)
        except Exception:
            # Backward compatability code for vmn 0.3.9:
            try:
                _tag_name = f"{tag_name}.0"
                commit_tag_obj = self._be.commit(_tag_name)
                tag_name = _tag_name
            except Exception:
                return tag_name, None

        return tag_name, commit_tag_obj

    @staticmethod
    def clone(path, remote):
        git.Repo.clone_from(f"{remote}", f"{path}")


class CommitMessageIterator:
    def __init__(self, iter_commits):
        self._iterator = iter(iter_commits)

    def __iter__(self):
        return self

    def __next__(self):
        commit = next(self._iterator)

        return commit.message.strip()


@measure_runtime_decorator
def get_client(root_path, be_type, inherit_env=False):
    if be_type == "local_file":
        be = LocalFileBackend(root_path)
        return be, None

    try:
        client = git.Repo(root_path, search_parent_directories=True)
        client.close()

        be = GitBackend(root_path, inherit_env)
        return be, None
    except git.exc.InvalidGitRepositoryError:
        err = f"repository path: {root_path} is not a functional git or repository.\n"
        return None, err


def parse_conventional_commit_message(message):
    match = CONVENTIONAL_COMMIT_PATTERN.match(message)
    if match:
        return match.groupdict()
    else:
        raise ValueError("Invalid commit message format")


def compare_release_modes(r1, r2):
    version_map = {
        "major": 3,
        "minor": 2,
        "patch": 1,
        "micro": 0,
    }

    return version_map[r1] >= version_map[r2]
