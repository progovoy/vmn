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
from logging.handlers import RotatingFileHandler
import traceback
import io

import git
import yaml

DEBUG_TRACE_ENV_VAR = "VMN_DEBUG_TRACE"

INIT_COMMIT_MESSAGE = "Initialized vmn tracking"

VMN_VERSION_FORMAT = (
    "{major}.{minor}.{patch}[.{hotfix}][-{prerelease}][+{buildmetadata}]"
)
VMN_DEFAULT_TEMPLATE = (
    "[{major}][.{minor}][.{patch}][.{hotfix}]" "[-{prerelease}][+{buildmetadata}]"
)

_SEMVER_VER_REGEX = (
    "(?P<major>0|[1-9]\d*)\." "(?P<minor>0|[1-9]\d*)\." "(?P<patch>0|[1-9]\d*)"
)

_SEMVER_PRERELEASE_REGEX = "(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"

SEMVER_BUILDMETADATA_REGEX = (
    "(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
)

SEMVER_REGEX = (
    f"^{_SEMVER_VER_REGEX}{_SEMVER_PRERELEASE_REGEX}{SEMVER_BUILDMETADATA_REGEX}$"
)

_VMN_HOTFIX_REGEX = "(?:\.(?P<hotfix>0|[1-9]\d*))?"

_VMN_VER_REGEX = f"{_SEMVER_VER_REGEX}" f"{_VMN_HOTFIX_REGEX}"

VMN_VER_REGEX = f"^{_VMN_VER_REGEX}$"

_VMN_REGEX = (
    f"{_VMN_VER_REGEX}" f"{_SEMVER_PRERELEASE_REGEX}" f"{SEMVER_BUILDMETADATA_REGEX}$"
)

# Regex for matching versions stamped by vmn
VMN_REGEX = f"^{_VMN_REGEX}$"

# TODO: create an abstraction layer on top of tag names versus the actual Semver versions
VMN_TAG_REGEX = f"^(?P<app_name>[^\/]+)_{_VMN_REGEX}$"

_VMN_ROOT_REGEX = "(?P<version>0|[1-9]\d*)"
VMN_ROOT_REGEX = f"^{_VMN_ROOT_REGEX}$"

VMN_ROOT_TAG_REGEX = f"^(?P<app_name>[^\/]+)_{_VMN_ROOT_REGEX}$"

VMN_TEMPLATE_REGEX = (
    "^(?:\[(?P<major_template>[^\{\}]*\{major\}[^\{\}]*)\])?"
    "(?:\[(?P<minor_template>[^\{\}]*\{minor\}[^\{\}]*)\])?"
    "(?:\[(?P<patch_template>[^\{\}]*\{patch\}[^\{\}]*)\])?"
    "(?:\[(?P<hotfix_template>[^\{\}]*\{hotfix\}[^\{\}]*)\])?"
    "(?:\[(?P<prerelease_template>[^\{\}]*\{prerelease\}[^\{\}]*)\])?"
    "(?:\[(?P<buildmetadata_template>[^\{\}]*\{buildmetadata\}[^\{\}]*)\])?$"
)

RELATIVE_TO_CURRENT_VCS_POSITION_TYPE = "current"
RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE = "branch"
RELATIVE_TO_GLOBAL_TYPE = "global"

VMN_USER_NAME = "vmn"
VMN_BE_TYPE_GIT = "git"
VMN_BE_TYPE_LOCAL_FILE = "local_file"

GLOBAL_LOG_FILENAME = "global_vmn.log"

LOGGER = None


# Create a custom execute function
def custom_execute(self, *args, **kwargs):
    if LOGGER is not None:
        try:
            if DEBUG_TRACE_ENV_VAR in os.environ:
                trace_str = io.StringIO()
                traceback.print_stack(file=trace_str)
                LOGGER.debug(f"Stacktrace:\n{trace_str.getvalue()}")

            LOGGER.debug(f"git cmd:\n{' '.join(str(v) for v in args[0])}")
        except Exception as exc:
            pass

    original_execute = getattr(self.__class__, '_execute')
    start_time = time.perf_counter()
    originally_extended_output = "with_extended_output" in kwargs
    kwargs["with_extended_output"] = True
    ret = original_execute(self, *args, **kwargs)

    ret_code = 0
    sout = ''
    serr = ''
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

    end_time = time.perf_counter()

    time_took = end_time - start_time

    if LOGGER is not None:
        LOGGER.debug(
            f"git cmd took: {time_took:.6f} seconds.\n"
            f"ret code: {ret_code}\n"
            f"out: {sout}\n"
            f"err: {serr}"
        )

    return ret


# Monkey-patch the Git class
git.cmd.Git._execute = git.cmd.Git.execute
git.cmd.Git.execute = custom_execute


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
    exist = os.path.exists(os.path.join(root_path, ".vmn")) or os.path.exists(
        os.path.join(root_path, ".git")
    )
    while not exist:
        try:
            prev_path = root_path
            root_path = os.path.realpath(os.path.join(root_path, ".."))
            if prev_path == root_path:
                raise RuntimeError()

            exist = os.path.exists(os.path.join(root_path, ".vmn")) or os.path.exists(
                os.path.join(root_path, ".git")
            )
        except Exception as exc:
            LOGGER.debug(f"Logged exception: ", exc_info=True)
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


def init_stamp_logger(rotating_log_path=None, debug=False):
    global LOGGER

    LOGGER = logging.getLogger(VMN_USER_NAME)
    clear_logger_handlers(LOGGER)
    global_logger = logging.getLogger()
    clear_logger_handlers(global_logger)

    global_logger.setLevel(logging.DEBUG)

    fmt = "[%(levelname)s] %(message)s"
    formatter = logging.Formatter(fmt, "%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    min_stdout_level = logging.INFO
    if debug:
        min_stdout_level = logging.DEBUG

    stdout_handler.addFilter(LevelFilter(min_stdout_level, logging.INFO))
    LOGGER.addHandler(stdout_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)
    LOGGER.addHandler(stderr_handler)

    if rotating_log_path is None:
        return LOGGER

    rotating_file_handler = init_log_file_handler(rotating_log_path)
    LOGGER.addHandler(rotating_file_handler)

    global_log_path = os.path.join(
        os.path.dirname(rotating_log_path),
        GLOBAL_LOG_FILENAME
    )
    global_file_handler = init_log_file_handler(global_log_path)
    global_logger.addHandler(global_file_handler)

    return LOGGER


def init_log_file_handler(rotating_log_path):
    rotating_file_handler = RotatingFileHandler(
        rotating_log_path,
        maxBytes=1024 * 1024 * 10,
        backupCount=1,
    )
    rotating_file_handler.setLevel(logging.DEBUG)
    fmt = f"%(pathname)s:%(lineno)d => %(asctime)s - [%(levelname)s] %(message)s"
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
    def __init__(self, type):
        self._type = type

    def __del__(self):
        pass

    def type(self):
        return self._type

    def prepare_for_remote_operation(self):
        return 0

    def get_first_reachable_version_info(
            self, app_name, root=False, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        return {}

    def get_active_branch(self):
        return "none"

    def remote(self):
        return "none"

    def last_user_changeset(self):
        return "none"

    @staticmethod
    def app_name_to_git_tag_app_name(app_name):
        return app_name.replace("/", "-")

    @staticmethod
    def gen_unique_id(verstr, hash):
        return f"{verstr}+{hash}"

    @staticmethod
    def get_utemplate_formatted_version(raw_vmn_version, template, hide_zero_hotfix):
        match = re.search(VMN_REGEX, raw_vmn_version)

        gdict = match.groupdict()
        if gdict["hotfix"] == "0" and hide_zero_hotfix:
            gdict["hotfix"] = None

        octats = (
            "major",
            "minor",
            "patch",
            "hotfix",
            "prerelease",
            "buildmetadata",
        )

        formatted_version = ""
        for octat in octats:
            if gdict[octat] is None:
                continue

            if (
                    f"{octat}_template" in template
                    and template[f"{octat}_template"] is not None
            ):
                d = {octat: gdict[octat]}
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
            version,
            hide_zero_hotfix,
            prerelease=None,
            prerelease_count=None,
            buildmetadata=None,
    ):
        app_name = VMNBackend.app_name_to_git_tag_app_name(app_name)

        verstr = VMNBackend.serialize_vmn_version(
            version,
            prerelease,
            prerelease_count,
            hide_zero_hotfix,
            buildmetadata,
        )

        verstr = f"{app_name}_{verstr}"

        match = re.search(VMN_TAG_REGEX, verstr)
        if match is None:
            err = f"Tag {verstr} doesn't comply with: " f"{VMN_TAG_REGEX} format"
            LOGGER.error(err)

            raise RuntimeError(err)

        return verstr

    @staticmethod
    def serialize_vmn_version(
            current_version,
            prerelease,
            prerelease_count,
            hide_zero_hostfix,
            buildmetadata=None,
    ):
        vmn_version = VMNBackend.get_base_vmn_version(
            current_version, hide_zero_hostfix
        )

        if prerelease is None or prerelease == "release":
            if buildmetadata is not None:
                vmn_version = f"{vmn_version}+{buildmetadata}"

            return vmn_version

        try:
            assert prerelease in prerelease_count
            # TODO: here try to use VMN_VERSION_FORMAT somehow
            vmn_version = f"{vmn_version}-{prerelease}{prerelease_count[prerelease]}"

            match = re.search(VMN_REGEX, vmn_version)
            if match is None:
                err = (
                    f"Tag {vmn_version} doesn't comply with: "
                    f"{VMN_VERSION_FORMAT} format"
                )
                LOGGER.error(err)

                raise RuntimeError(err)
        except AssertionError:
            LOGGER.error(
                f"{prerelease} doesn't appear in {prerelease_count} "
                "Turn on debug mode to see traceback"
            )
            LOGGER.debug("Exception info: ", exc_info=True)

        if buildmetadata is not None:
            vmn_version = f"{vmn_version}+{buildmetadata}"

            match = re.search(VMN_REGEX, vmn_version)
            if match is None:
                err = (
                    f"Tag {vmn_version} doesn't comply with: "
                    f"{VMN_VERSION_FORMAT} format"
                )
                LOGGER.error(err)
                raise RuntimeError(err)

        return vmn_version

    @staticmethod
    def serialize_vmn_version_hotfix(
            hide_zero_hotfix, major, minor, patch, hotfix=None
    ):
        if hide_zero_hotfix and hotfix == "0":
            hotfix = None

        vmn_version = f"{major}.{minor}.{patch}"
        if hotfix is not None:
            vmn_version = f"{vmn_version}.{hotfix}"

        return vmn_version

    @staticmethod
    def get_base_vmn_version(current_version, hide_zero_hotfix):
        match = re.search(VMN_REGEX, current_version)
        gdict = match.groupdict()
        if gdict["hotfix"] is None:
            gdict["hotfix"] = str(0)
        vmn_version = VMNBackend.serialize_vmn_version_hotfix(
            hide_zero_hotfix,
            gdict["major"],
            gdict["minor"],
            gdict["patch"],
            gdict["hotfix"],
        )

        return vmn_version

    @staticmethod
    def deserialize_tag_name(some_tag):
        ret = {
            "app_name": None,
            "type": "version",
            "version": None,
            "root_version": None,
            "major": None,
            "minor": None,
            "patch": None,
            "hotfix": None,
            "prerelease": None,
            "buildmetadata": None,
        }

        match = re.search(VMN_ROOT_TAG_REGEX, some_tag)
        if match is not None:
            gdict = match.groupdict()

            int(gdict["version"])
            ret["root_version"] = gdict["version"]
            ret["app_name"] = gdict["app_name"]
            ret["type"] = "root"

            return ret

        match = re.search(VMN_TAG_REGEX, some_tag)
        if match is None:
            raise WrongTagFormatException()

        gdict = match.groupdict()
        ret["app_name"] = gdict["app_name"].replace("-", "/")
        ret["version"] = f'{gdict["major"]}.{gdict["minor"]}.{gdict["patch"]}'
        ret["major"] = gdict["major"]
        ret["minor"] = gdict["minor"]
        ret["patch"] = gdict["patch"]
        ret["hotfix"] = "0"

        if gdict["hotfix"] is not None:
            ret["hotfix"] = gdict["hotfix"]

        # TODO: Think about what it means that we have the whole
        #  prerelease string here (with the prerelease count).
        #  At least rename other prerelease prefixes to
        #  something like "prerelease mode" or "prerelease prefix"
        if gdict["prerelease"] is not None:
            ret["prerelease"] = gdict["prerelease"]
            ret["type"] = "prerelease"

        if gdict["buildmetadata"] is not None:
            ret["buildmetadata"] = gdict["buildmetadata"]
            ret["type"] = "buildmetadata"

        return ret

    @staticmethod
    def enhance_ver_info(ver_infos):
        all_tags = {}
        for tag, ver_info_c in ver_infos.items():
            tagd = VMNBackend.deserialize_vmn_tag_name(tag)
            tagd.update({"tag": tag})
            tagd["message"] = ver_info_c["ver_info"]

            all_tags[tagd["type"]] = tagd

            # TODO:: Check API commit version
        # Enhance "raw" ver_infos so all tags will have all info
        for t, v in ver_infos.items():
            if "root_app" not in v["ver_info"]["stamping"] and "root" in all_tags:
                v["ver_info"]["stamping"].update(
                    all_tags["root"]["message"]["stamping"]
                )
            elif "app" not in v["ver_info"]["stamping"] and "version" in all_tags:
                v["ver_info"]["stamping"].update(
                    all_tags["version"]["message"]["stamping"]
                )

    @staticmethod
    def deserialize_vmn_tag_name(vmn_tag):
        try:
            return VMNBackend.deserialize_tag_name(vmn_tag)
        except WrongTagFormatException as exc:
            LOGGER.error(
                f"Tag {vmn_tag} doesn't comply to vmn version format",
                exc_info=True,
            )

            raise exc
        except Exception as exc:
            LOGGER.error(
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
        if tagd["type"] == "root":
            dir_path = os.path.join(
                self.repo_path, ".vmn", tagd["app_name"], "root_verinfo"
            )
            path = os.path.join(dir_path, f"{tagd['root_version']}.yml")
        else:
            dir_path = os.path.join(self.repo_path, ".vmn", tagd["app_name"], "verinfo")
            path = os.path.join(dir_path, f"{tagd['version']}.yml")

        ver_infos = {
            tag_name: {"ver_info": None, "tag_object": None, "commit_object": None}
        }
        try:
            with open(path, "r") as f:
                ver_infos[tag_name]["ver_info"] = yaml.safe_load(f)
        except Exception as exc:
            LOGGER.error("Logged Exception message:", exc_info=True)

        return tag_name, ver_infos


class GitBackend(VMNBackend):
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
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        except Exception as exc:
            LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remotes[0].urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception as exc:
            LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        finally:
            client.close()

        return hash, remote, "git"

    def is_path_tracked(self, path):
        try:
            self._be.git.execute(["git", "ls-files", "--error-unmatch", path])
            return True
        except Exception as exc:
            LOGGER.debug(f"Logged exception for path {path}: ", exc_info=True)
            return False

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
                self.selected_remote.push(refspec=f"refs/tags/{tag}", o="ci.skip")
            except Exception:
                self.selected_remote.push(refspec=f"refs/tags/{tag}")

    def push(self, tags=()):
        if self.detached_head:
            raise RuntimeError("Will not push from detached head")

        if self.remote_active_branch is None:
            raise RuntimeError("Will not push remote branch does not exist")

        remote_branch_name_no_remote_name = "".join(
            self.remote_active_branch.split(f"{self.selected_remote.name}/")
        )

        try:
            ret = self.selected_remote.push(
                refspec=f"refs/heads/{self.active_branch}:{remote_branch_name_no_remote_name}",
                o="ci.skip",
            )
        except Exception as exc:
            ret = self.selected_remote.push(
                refspec=f"refs/heads/{self.active_branch}:{remote_branch_name_no_remote_name}"
            )

        if ret[0].old_commit is None:
            if "up to date" in ret[0].summary:
                LOGGER.warning(
                    "GitPython library has failed to push because we are "
                    "up to date already. How can it be? "
                )
            else:
                LOGGER.error("Push has failed. Please verify that 'git push' works")
                raise Warning(
                    f"Push has failed because: {ret[0].summary}.\n"
                    "Please verify that 'git push' works"
                )

        for tag in tags:
            try:
                self.selected_remote.push(refspec=f"refs/tags/{tag}", o="ci.skip")
            except Exception:
                self.selected_remote.push(refspec=f"refs/tags/{tag}")

    def pull(self):
        if self.detached_head:
            raise RuntimeError("Will not pull in detached head")

        self.selected_remote.pull("--ff-only")

    def commit(self, message, user, include=None):
        if include is not None:
            for file in include:
                self._be.index.add(file)
        author = git.Actor(user, user)

        self._be.index.commit(message=message, author=author)

    def root(self):
        return self._be.working_dir

    def status(self, tag):
        found_tag = self._be.tag(f"refs/tags/{tag}")
        try:
            return tuple(found_tag.commit.stats.files)
        except Exception as exc:
            LOGGER.debug(f"Logged exception: ", exc_info=True)
            return None

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
            cmd_suffix = f"--branches"

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

    def _get_first_reachable_vmn_stamp_tag_list(self, app_name, cmd_suffix, msg_filter):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)
        bug_limit = 0
        while not ver_infos and bug_limit < 100:
            if cobj is None:
                break

            cmd_suffix = f"{cobj.hexsha}~1"
            cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

            bug_limit += 1
            if bug_limit == 100:
                LOGGER.warning(
                    f"Probable bug: vmn failed to find "
                    f"vmn's commit after 100 interations."
                )
                ver_infos = {}
                break

        tag_objects = []
        for k in ver_infos:
            tag_objects.append(ver_infos[k]["tag_object"])

        # We want the newest tag on top because we skip "buildmetadata tags"
        # TODO:: solve the weird coupling between here and get_first_reachable_version_info
        tag_objects = sorted(
            tag_objects, key=lambda t: t.object.tagged_date, reverse=True
        )
        tag_names = []
        for tag_object in tag_objects:
            tag_names.append(tag_object.name)

        return tag_names, cobj, ver_infos

    def _get_shallow_first_reachable_vmn_stamp_tag_list(
            self, app_name, cmd_suffix, msg_filter
    ):
        cobj, ver_infos = self._get_top_vmn_commit(app_name, cmd_suffix, msg_filter)

        if ver_infos:
            tag_objects = []
            for k in ver_infos:
                tag_objects.append(ver_infos[k]["tag_object"])

            # We want the newest tag on top because we skip "buildmetadata tags"
            # TODO:: solve the weird coupling between here and get_first_reachable_version_info
            tag_objects = sorted(
                tag_objects, key=lambda t: t.object.tagged_date, reverse=True
            )
            tag_names = []
            for tag_object in tag_objects:
                tag_names.append(tag_object.name)

            return tag_names, cobj, ver_infos

        tag_name_prefix = VMNBackend.app_name_to_git_tag_app_name(app_name)
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
        except Exception as exc:
            LOGGER.error(f"Failed to get tag object from tag name: {latest_tag}")
            return [], cobj, ver_infos

        ver_infos = self.get_all_commit_tags(found_tag.commit.hexsha)
        tag_objects = []

        for k in ver_infos.keys():
            if ver_infos[k]["tag_object"]:
                tag_objects.append(ver_infos[k]["tag_object"])

        # We want the newest tag on top because we skip "buildmetadata tags"
        # TODO:: solve the weird coupling between here and get_first_reachable_version_info
        tag_objects = sorted(
            tag_objects, key=lambda t: t.object.tagged_date, reverse=True
        )

        final_list_of_tag_names = []
        for tag_object in tag_objects:
            final_list_of_tag_names.append(tag_object.name)

        return final_list_of_tag_names, found_tag.commit, ver_infos

    def _get_top_vmn_commit(self, app_name, cmd_suffix, msg_filter):
        cmd = [
            f"--grep={msg_filter}",
            f"-1",
            f"--author={VMN_USER_NAME}",
            "--pretty=%H,,,%D",
            "--decorate=short",
            cmd_suffix,
        ]
        LOGGER.debug(f"Going to run: git log {' '.join(cmd)}")
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

    def get_latest_available_tag(self, tag_prefix_filter):
        cmd = ["--sort", "taggerdate", "--list", tag_prefix_filter]
        tag_names = self._be.git.tag(*cmd).split("\n")

        if len(tag_names) == 1 and tag_names[0] == "":
            return None

        return tag_names[-1]

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

    def get_tag_object_from_tag_name(self, tname):
        try:
            o = self._be.tag(f"refs/tags/{tname}")
        except Exception as exc:
            LOGGER.debug(f"Logged exception: ", exc_info=True)
            # Backward compatability code for vmn 0.3.9:
            try:
                _tag_name = f"{tname}.0"
                o = self._be.tag(f"refs/tags/{tname}")
                tag_name = _tag_name
            except Exception as exc:
                LOGGER.debug(f"Logged exception: ", exc_info=True)
                return tname, None

        try:
            if o.commit.author.name != "vmn":
                return tname, None
        except Exception as exc:
            LOGGER.debug("Exception info: ", exc_info=True)
            return tname, None

        if o.tag is None:
            return tname, None

        if o is None:
            LOGGER.debug(f"Somehow did not find a tag object for tag: {tname}")

        return tname, o

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
            except Exception as exc:
                LOGGER.debug(f"Skipped on {hexsha} commit")

        for tname in cleaned_tags:
            tname, ver_info_c = self.parse_tag_message(tname)
            if ver_info_c["ver_info"] is None:
                LOGGER.debug(
                    f"Probably non-vmn tag - {tname} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[tname] = ver_info_c

        return ver_infos

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
                LOGGER.debug(
                    f"Probably non-vmn tag - {t} with tag msg: {ver_info_c['ver_info']}. Skipping ",
                    exc_info=True,
                )
                continue

            ver_infos[t] = ver_info_c

        return ver_infos

    def get_all_brother_tags(self, tag_name):
        try:
            sha = self.changeset(tag=tag_name)
            ver_infos = self.get_all_commit_tags(sha)
        except Exception as exc:
            LOGGER.debug(
                f"Failed to get brother tags for tag: {tag_name}. "
                f"Logged exception: ",
                exc_info=True,
            )
            return []

        return ver_infos

    def in_detached_head(self):
        return self._be.head.is_detached

    def add_git_user_cfg_if_missing(self):
        try:
            self._be.config_reader().get_value("user", "name")
            self._be.config_reader().get_value("user", "email")
        except (configparser.NoSectionError, configparser.NoOptionError):
            # git user name or email configuration is missing, add default override
            self._be.git.set_persistent_git_options(
                c=[f'user.name="{VMN_USER_NAME}"', f'user.email="{VMN_USER_NAME}"']
            )

    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = f"Pending changes in {self.root()}."
            return err

        return None

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

    def checkout_branch(self, branch_name=None):
        try:
            if branch_name is None:
                branch_name = self.active_branch

            self.checkout(branch=branch_name)
        except Exception as exc:
            logging.error("Failed to get branch name")
            LOGGER.debug("Exception info: ", exc_info=True)

            return None

        return self._be.active_branch.commit.hexsha

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
            except Exception as exc:
                LOGGER.warning(
                    f"Found remote branch {ret} however it belongs to a "
                    f"different remote that vmn has selected to work with. "
                    f"Will behave like no remote was found. The remote that vmn has "
                    f"selected to work with is: {self.selected_remote.name}"
                )

                return None

            return ret
        except Exception as exc:
            return None

    def prepare_for_remote_operation(self):
        if self.remote_active_branch is not None:
            return 0

        local_branch_name = self.active_branch

        LOGGER.warning(
            f"No remote branch for local branch: {local_branch_name} "
            f"was found. Will try to set upstream for it"
        )

        out = self._be.git.branch("-r", "--contains", "HEAD")
        out = out.split("\n")[0].strip()
        if not out:
            out = f"{self.selected_remote.name}/{local_branch_name}"

        try:
            self._be.git.execute(
                ["git", "remote", "set-branches", "--add",
                 self.selected_remote.name, local_branch_name]
            )
            self._be.git.branch(f"--set-upstream-to={out}", local_branch_name)
        except Exception as exc:
            LOGGER.debug(
                f"Failed to set upstream branch for {local_branch_name}:", exc_info=True
            )
            return 1

        self.remote_active_branch = out

        return 0

    def get_active_branch(self):
        # TODO:: return the full ref name: refs/heads/..
        if not self.in_detached_head():
            active_branch = self._be.active_branch.name
        else:
            active_branch = self.get_branch_from_changeset(self._be.head.commit.hexsha)

        return active_branch

    def get_branch_from_changeset(self, hexsha):
        out = self._be.git.branch("--contains", hexsha)
        out = out.split("\n")[1:]
        if not out:
            # TODO:: add debug print here
            out = self._be.git.branch().split("\n")[1:]

        active_branches = []
        for item in out:
            active_branches.append(item.strip())
        if len(active_branches) > 1:
            LOGGER.info(
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

            LOGGER.debug(
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

    def checkout(self, rev=None, tag=None, branch=None):
        if tag is not None:
            # TODO:: maybe it issafer to
            rev = f"refs/tags/{tag}"
        elif branch is not None:
            # TODO:: : f"refs/heads/{branch}"
            rev = f"{branch}"

        assert rev is not None

        self._be.git.checkout(rev)

        self.detached_head = self.in_detached_head()

    @staticmethod
    def get_actual_deps_state(vmn_root_path, paths):
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

    def last_user_changeset(self):
        p = self._be.head.commit
        if p.author.name == VMN_USER_NAME:
            if p.message.startswith(INIT_COMMIT_MESSAGE):
                return p.hexsha

            ver_infos = self.get_all_commit_tags(p.hexsha)
            if not ver_infos:
                LOGGER.warning(
                    f"Somehow vmn's commit {p.hexsha} has no tags. "
                    f"Check your repo. Assuming this commit is a user commit"
                )
                return p.hexsha

            for t, v in ver_infos.items():
                if "stamping" in v["ver_info"]:
                    return v["ver_info"]["stamping"]["app"]["changesets"]["."]["hash"]

            LOGGER.warning(
                f"Somehow vmn's commit {p.hexsha} has no tags that are parsable. "
                f"Check your repo. Assuming this commit is a user commit"
            )
            return p.hexsha

        return p.hexsha

    def remote(self):
        remote = tuple(self.selected_remote.urls)[0]

        if os.path.isdir(remote):
            remote = os.path.relpath(remote, self.root())

        return remote

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
        except Exception as exc:
            LOGGER.debug(f"Logged exception: ", exc_info=True)
            return None

    def revert_local_changes(self, files=[]):
        if files:
            try:
                try:
                    for f in files:
                        self._be.git.reset(f)
                except Exception as exc:
                    LOGGER.debug(f"Failed to git reset files: {files}", exc_info=True)

                self._be.index.checkout(files, force=True)
            except Exception as exc:
                LOGGER.debug(f"Failed to git checkout files: {files}", exc_info=True)

    def revert_vmn_commit(self, prev_changeset, version_files, tags=[]):
        self.revert_local_changes(version_files)

        # TODO: also validate that the commit is
        #  currently worked on app name
        if self.changeset() == prev_changeset:
            return

        if self._be.active_branch.commit.author.name != VMN_USER_NAME:
            LOGGER.error("BUG: Will not revert non-vmn commit.")
            raise RuntimeError()

        self._be.git.reset("--hard", "HEAD~1")
        for tag in tags:
            try:
                self._be.delete_tag(tag)
            except Exception:
                LOGGER.info(f"Failed to remove tag {tag}")
                LOGGER.debug("Exception info: ", exc_info=True)

                continue

        try:
            self._be.git.fetch("--tags")
        except Exception:
            LOGGER.info("Failed to fetch tags")
            LOGGER.debug("Exception info: ", exc_info=True)

    def get_first_reachable_version_info(
            self, app_name, root_context=False, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        app_tags, cobj, ver_infos = self.get_latest_stamp_tags(
            app_name, root_context, type
        )

        if root_context:
            regex = VMN_ROOT_TAG_REGEX
        else:
            regex = VMN_TAG_REGEX

        cleaned_app_tag = None
        for tag in app_tags:
            # skip buildmetadata versions
            if "+" in tag:
                continue

            match = re.search(regex, tag)
            if match is None:
                continue

            gdict = match.groupdict()

            if gdict["app_name"] != app_name.replace("/", "-"):
                continue

            cleaned_app_tag = tag
            break

        if cleaned_app_tag is None:
            return None, {}

        if cleaned_app_tag not in ver_infos:
            LOGGER.debug(f"Somehow {cleaned_app_tag} not in ver_infos")
            return None, {}

        VMNBackend.enhance_ver_info(ver_infos)

        return cleaned_app_tag, ver_infos

    def get_tag_version_info(self, tag_name):
        ver_infos = {}
        tag_name, commit_tag_obj = self.get_commit_object_from_tag_name(tag_name)
        if commit_tag_obj is None:
            LOGGER.debug(f"Tried to find {tag_name} but with no success")
            return tag_name, ver_infos

        if commit_tag_obj.author.name != VMN_USER_NAME:
            LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ver_infos

        # "raw" ver_infos
        ver_infos = self.get_all_brother_tags(tag_name)
        if tag_name not in ver_infos:
            LOGGER.debug(f"Could not find version info for {tag_name}")
            return tag_name, None

        VMNBackend.enhance_ver_info(ver_infos)

        return tag_name, ver_infos

    def parse_tag_message(self, tag_name):
        tag_name, tag_obj = self.get_tag_object_from_tag_name(tag_name)

        ret = {"ver_info": None, "tag_object": tag_obj, "commit_object": None}
        if not tag_obj:
            return tag_name, ret

        commit_tag_obj = tag_obj.commit
        if commit_tag_obj is None or commit_tag_obj.author.name != VMN_USER_NAME:
            LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, ret

        ret["commit_object"] = commit_tag_obj

        # TODO:: Check API commit version
        # safe_load discards any text before the YAML document (if present)
        ver_info = yaml.safe_load(tag_obj.object.message)
        if ver_info is None:
            return tag_name, ret

        if type(ver_info) is not dict and ver_info.startswith("Automatic"):
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
            LOGGER.debug(f"vmn_info key was not found in tag {tag_name}")
            return tag_name, ret

        ret["ver_info"] = ver_info

        return tag_name, ret

    def get_commit_object_from_commit_hex(self, hex):
        return self._be.commit(hex)

    def get_commit_object_from_tag_name(self, tag_name):
        try:
            commit_tag_obj = self._be.commit(tag_name)
        except Exception as exc:
            # Backward compatability code for vmn 0.3.9:
            try:
                _tag_name = f"{tag_name}.0"
                commit_tag_obj = self._be.commit(_tag_name)
                tag_name = _tag_name
            except Exception as exc:
                return tag_name, None

        return tag_name, commit_tag_obj

    @staticmethod
    def clone(path, remote):
        git.Repo.clone_from(f"{remote}", f"{path}")


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
