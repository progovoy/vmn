#!/usr/bin/env python3
import argparse
import random
import time
from pathlib import Path
import copy
import yaml
import sys
import os
import pathlib
from filelock import FileLock
from multiprocessing import Pool
import re
from packaging import version as pversion

CUR_PATH = "{0}/".format(os.path.dirname(__file__))
VER_FILE_NAME = "last_known_app_version.yml"
IGNORED_FILES = ["vmn.lock"]

sys.path.append(CUR_PATH)

import version as version_mod
from stamp_utils import HostState
import stamp_utils

LOGGER = stamp_utils.init_stamp_logger()


class VMNContextMAnagerManager(object):
    def __init__(self, command_line):
        self.args = parse_user_commands(command_line)
        cwd = os.getcwd()
        if "VMN_WORKING_DIR" in os.environ:
            cwd = os.environ["VMN_WORKING_DIR"]

        root = False
        if "root" in self.args:
            root = self.args.root
        initial_params = {
            "root": root,
            "cwd": cwd,
            "name": None,
            "release_mode": None,
            "prerelease": None,
        }

        if "name" in self.args and self.args.name:
            validate_app_name(self.args)
            initial_params["name"] = self.args.name
        if "release_mode" in self.args and self.args.release_mode:
            initial_params["release_mode"] = self.args.release_mode
            # For backward compatability
            if initial_params["release_mode"] == "micro":
                initial_params["release_mode"] = "hotfix"
        if "pr" in self.args and self.args.pr and self.args.pr != "release":
            initial_params["prerelease"] = self.args.pr

        params = build_world(
            initial_params["name"],
            initial_params["cwd"],
            initial_params["root"],
            initial_params["release_mode"],
            initial_params["prerelease"],
        )

        vmn_path = os.path.join(params["root_path"], ".vmn")
        lock_file_path = os.path.join(vmn_path, "vmn.lock")
        pathlib.Path(os.path.dirname(lock_file_path)).mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(lock_file_path)
        self.params = params
        self.vcs = None
        self.lock_file_path = lock_file_path

        global LOGGER
        LOGGER = stamp_utils.init_stamp_logger(self.args.debug)

    def __enter__(self):
        self.lock.acquire()
        self.vcs = VersionControlStamper(self.params)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.vcs is not None:
            del self.vcs

        self.lock.release()


class IVersionsStamper(object):
    def __init__(self, conf):
        self._name = conf["name"]
        self._root_path = conf["root_path"]
        self.backend, _ = stamp_utils.get_client(self._root_path)
        self._release_mode = conf["release_mode"]
        self._prerelease = conf["prerelease"]
        self._buildmetadata = conf["buildmetadata"]
        self._repo_name = "."
        self._should_publish = True

        self.current_version_info = {
            "vmn_info": {
                "description_message_version": "1.1",
                "vmn_version": version_mod.version,
            },
            "stamping": {
                "msg": "",
                "app": {
                    "info": {},
                },
                "root_app": {},
            },
        }

        if conf["name"] is None:
            self.tracked = False
            return

        self._app_dir_path = conf["app_dir_path"]
        self._app_conf_path = conf["app_conf_path"]
        self._root_app_name = conf["root_app_name"]
        self._root_app_conf_path = conf["root_app_conf_path"]
        self._root_app_dir_path = conf["root_app_dir_path"]
        self._extra_info = conf["extra_info"]
        self._version_file_path = conf["version_file_path"]

        try:
            self.template = IVersionsStamper.parse_template(conf["template"])
            self.bad_format_template = False
        except:
            self.template = IVersionsStamper.parse_template(
                stamp_utils.VMN_DEFAULT_TEMPLATE
            )
            self.template_err_str = (
                "Failed to parse template: "
                f"{conf['template']}. "
                f"Falling back to default one: "
                f"{stamp_utils.VMN_DEFAULT_TEMPLATE}"
            )

            self.bad_format_template = True

        self._raw_configured_deps = conf["raw_configured_deps"]
        self.actual_deps_state = conf["actual_deps_state"]
        self._flat_configured_deps = self.get_deps_changesets()
        # TODO: refactor
        self._hide_zero_hotfix = conf["hide_zero_hotfix"]

        # TODO: this is ugly
        root_context = self._root_app_name == self._name
        self.ver_info_form_repo = self.backend.get_vmn_version_info(
            self._name, root_context
        )
        self.tracked = self.ver_info_form_repo is not None

        if root_context:
            return

        self.current_version_info = {
            "vmn_info": {
                "description_message_version": "1.1",
                "vmn_version": version_mod.version,
            },
            "stamping": {
                "app": {
                    "name": self._name,
                    "changesets": self.actual_deps_state,
                },
                "root_app": {},
            },
        }

        if self.tracked and self._release_mode is None:
            self.current_version_info["stamping"]["app"][
                "release_mode"
            ] = self.ver_info_form_repo["stamping"]["app"]["release_mode"]

        if self._root_app_name is not None:
            self.current_version_info["stamping"]["root_app"] = {
                "name": self._root_app_name,
                "latest_service": self._name,
                "services": {},
                "external_services": {},
            }

    def __del__(self):
        del self.backend

    # Note: this function generates
    # a version (including prerelease)
    def gen_app_version(
        self, initial_version, initial_prerelease, initial_prerelease_count
    ):
        if initial_prerelease == "release" and self._release_mode is None:
            raise RuntimeError(
                "When stamping from a previous release version, "
                "a release mode must be specified"
            )

        match = re.search(stamp_utils.VMN_REGEX, initial_version)
        gdict = match.groupdict()
        if gdict["hotfix"] is None:
            gdict["hotfix"] = str(0)

        match = re.search(
            stamp_utils.VMN_REGEX,
            self.ver_info_form_repo["stamping"]["app"]["_version"],
        )
        repo_gdict = match.groupdict()
        if repo_gdict["hotfix"] is None:
            repo_gdict["hotfix"] = str(0)

        major, minor, patch, hotfix = self._advance_version(gdict)

        prerelease = self._prerelease
        # If user did not specify a change in prerelease,
        # stay with the previous one
        if prerelease is None and self._release_mode is None:
            prerelease = initial_prerelease
        prerelease_count = copy.deepcopy(initial_prerelease_count)

        # Continue from last stamp prerelease information as long as
        # the last version is coherent with what is requested from
        # the version file or manual version (not yet implemented)
        prerelease, prerelease_count = self._advance_prerelease(
            prerelease, prerelease_count
        )

        verstr = self.gen_vmn_version(
            major,
            minor,
            patch,
            hotfix,
        )

        return verstr, prerelease, prerelease_count

    def _advance_prerelease(self, prerelease, prerelease_count):
        if prerelease is None:
            return None, {}
        if prerelease == "release":
            try:
                raise RuntimeError()
            except RuntimeError:
                LOGGER.error(
                    "prerelease equals to 'release' somehow. "
                    "Turn on debug mode to see traceback"
                )
                LOGGER.debug("Exception info: ", exc_info=True)

            return None, {}

        _prerelease_count = copy.deepcopy(prerelease_count)
        counter_key = f"{prerelease}"
        if counter_key not in _prerelease_count:
            _prerelease_count[counter_key] = 0

        _prerelease_count[counter_key] += 1

        if self._release_mode is not None:
            _prerelease_count = {
                counter_key: 1,
            }

        return counter_key, _prerelease_count

    def _advance_version(self, gdict):
        major = gdict["major"]
        minor = gdict["minor"]
        patch = gdict["patch"]
        hotfix = gdict["hotfix"]

        if self._release_mode == "major":
            major = str(int(major) + 1)
            minor = str(0)
            patch = str(0)
            hotfix = str(0)
        elif self._release_mode == "minor":
            minor = str(int(minor) + 1)
            patch = str(0)
            hotfix = str(0)
        elif self._release_mode == "patch":
            patch = str(int(patch) + 1)
            hotfix = str(0)
        elif self._release_mode == "hotfix":
            hotfix = str(int(hotfix) + 1)

        return major, minor, patch, hotfix

    def gen_vmn_version(
        self, major, minor, patch, hotfix=None, prerelease=None, prerelease_count={}
    ):
        if self._hide_zero_hotfix and hotfix == "0":
            hotfix = None

        vmn_version = f"{major}.{minor}.{patch}"
        if hotfix is not None:
            vmn_version = f"{vmn_version}.{hotfix}"
        if prerelease is not None and prerelease != "release":
            try:
                assert prerelease in prerelease_count
                vmn_version = (
                    f"{vmn_version}-{prerelease}{prerelease_count[prerelease]}"
                )
            except AssertionError:
                LOGGER.error(
                    f"{prerelease} doesn't appear in {prerelease_count} "
                    "Turn on debug mode to see traceback"
                )
                LOGGER.debug("Exception info: ", exc_info=True)

        return vmn_version

    @staticmethod
    def parse_template(template: str) -> object:
        match = re.search(stamp_utils.VMN_TEMPLATE_REGEX, template)

        gdict = match.groupdict()

        return gdict

    @staticmethod
    def write_version_to_file(
        file_path: str,
        version_number: str,
        prerelease: str,
        prerelease_count: dict,
    ) -> None:
        if prerelease is None:
            prerelease = "release"

        # this method will write the stamped ver of an app to a file,
        # weather the file pre exists or not
        try:
            with open(file_path, "w") as fid:
                ver_dict = {
                    "version_to_stamp_from": version_number,
                    "prerelease": prerelease,
                    "prerelease_count": prerelease_count,
                }
                yaml.dump(ver_dict, fid)
        except IOError as e:
            LOGGER.error(f"Error writing ver file: {file_path}\n")
            LOGGER.debug("Exception info: ", exc_info=True)

            raise IOError(e)
        except Exception as e:
            LOGGER.debug(e, exc_info=True)
            raise RuntimeError(e)

    def get_deps_changesets(self):
        flat_dependency_repos = []

        # resolve relative paths
        for rel_path, v in self._raw_configured_deps.items():
            for repo in v:
                flat_dependency_repos.append(
                    os.path.relpath(
                        os.path.join(self.backend.root(), rel_path, repo),
                        self.backend.root(),
                    ),
                )

        return flat_dependency_repos

    def get_be_formatted_version(self, version):
        return stamp_utils.VersionControlBackend.get_utemplate_formatted_version(
            version, self.template, self._hide_zero_hotfix
        )

    def find_matching_version(self, version, prerelease, prerelease_count):
        raise NotImplementedError("Please implement this method")

    def create_config_files(self, params):
        # If there is no file - create it
        if not os.path.isfile(self._app_conf_path):
            pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
                parents=True, exist_ok=True
            )

            ver_conf_yml = {
                "conf": {
                    "template": params["template"],
                    "deps": self._raw_configured_deps,
                    "extra_info": self._extra_info,
                    "hide_zero_hotfix": True,
                },
            }

            with open(self._app_conf_path, "w+") as f:
                msg = (
                    "# Autogenerated by vmn. You can edit this " "configuration file\n"
                )
                f.write(msg)
                yaml.dump(ver_conf_yml, f, sort_keys=True)

        if self._root_app_name is None:
            return

        if os.path.isfile(self._root_app_conf_path):
            return

        pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
            parents=True, exist_ok=True
        )

        ver_yml = {
            "conf": {"external_services": {}},
        }

        with open(self._root_app_conf_path, "w+") as f:
            f.write("# Autogenerated by vmn\n")
            yaml.dump(ver_yml, f, sort_keys=True)

    def stamp_app_version(
        self,
        initial_version,
        prerelease,
        prerelease_count,
    ):
        raise NotImplementedError("Please implement this method")

    def stamp_root_app_version(self, override_version=None):
        raise NotImplementedError("Please implement this method")

    def retrieve_remote_changes(self):
        raise NotImplementedError("Please implement this method")

    def publish_stamp(self, app_version, prerelease, prerelease_count, main_version):
        raise NotImplementedError("Please implement this method")


class VersionControlStamper(IVersionsStamper):
    def __init__(self, conf):
        IVersionsStamper.__init__(self, conf)

    def gen_verstr(self, current_version, prerelease, prerelease_count):
        match = re.search(stamp_utils.VMN_REGEX, current_version)
        gdict = match.groupdict()
        if gdict["hotfix"] is None:
            gdict["hotfix"] = str(0)
        verstr = self.gen_vmn_version(
            gdict["major"],
            gdict["minor"],
            gdict["patch"],
            gdict["hotfix"],
            prerelease,
            prerelease_count,
        )

        return verstr

    def find_matching_version(self, version, prerelease, prerelease_count):
        tag_formatted_app_name = (
            stamp_utils.VersionControlBackend.get_tag_formatted_app_name(
                self._name,
                version,
                prerelease,
                prerelease_count,
            )
        )

        # Try to find any version of the application matching the
        # user's repositories local state
        _, ver_info = self.backend.get_vmn_tag_version_info(tag_formatted_app_name)
        if ver_info is None:
            return None

        # Can happen if app's name is a prefix of another app
        if ver_info["stamping"]["app"]["name"] != self._name:
            return None

        if ver_info["stamping"]["app"]["release_mode"] == "init":
            return None

        found = True
        for k, v in ver_info["stamping"]["app"]["changesets"].items():
            if k not in self.actual_deps_state:
                found = False
                break

            # when k is the "main repo" repo
            if self._repo_name == k:
                user_changeset = self.backend.last_user_changeset()

                if v["hash"] != user_changeset:
                    found = False
                    break
            elif v["hash"] != self.actual_deps_state[k]["hash"]:
                found = False
                break

        if found:
            return ver_info

        return None

    @staticmethod
    def get_version_number_from_file(version_file_path) -> str or None:
        with open(version_file_path, "r") as fid:
            ver_dict = yaml.safe_load(fid)
            if "version_to_stamp_from" in ver_dict:
                if "prerelease" not in ver_dict or "prerelease" not in ver_dict:
                    # Backward for 0.4.0-rc6
                    return (
                        ver_dict["version_to_stamp_from"],
                        "release",
                        {},
                    )

                return (
                    ver_dict["version_to_stamp_from"],
                    ver_dict["prerelease"],
                    ver_dict["prerelease_count"],
                )

            # Backward compatible vmn 0.3.9 code
            if "prerelease" not in ver_dict:
                return (
                    ver_dict["last_stamped_version"],
                    "release",
                    {},
                )

            return (
                ver_dict["last_stamped_version"],
                ver_dict["prerelease"],
                ver_dict["prerelease_count"],
            )

    def add_to_version(self):
        if not self._buildmetadata:
            raise RuntimeError("TODO xxx")

        old_version = VersionControlStamper.get_version_number_from_file(
            self._version_file_path
        )

        self._should_publish = False
        tag_name = stamp_utils.VersionControlBackend.get_tag_formatted_app_name(
            self._name, old_version
        )
        if self.backend.changeset() != self.backend.changeset(tag=tag_name):
            raise RuntimeError(
                "Releasing a release candidate is only possible when the repository "
                "state is on the exact version. Please vmn goto the version you'd "
                "like to release."
            )

        (
            _,
            _,
            version,
            hotfix,
            prerelease,
            _,
            _,
        ) = stamp_utils.VersionControlBackend.get_tag_properties(tag_name)

        if not self._hide_zero_hotfix:
            version = f"{version}.{hotfix}"
        elif hotfix != "0":
            version = f"{version}.{hotfix}"
        if prerelease is not None:
            version = f"{version}-{prerelease}"

        version = f"{version}+{self._buildmetadata}"

        tag_name = stamp_utils.VersionControlBackend.get_tag_formatted_app_name(
            self._name, version
        )

        messages = [
            yaml.dump({"key": "TODO "}, sort_keys=True),
        ]

        self.backend.tag([tag_name], messages)

        return version

    def release_app_version(self, verstr):
        tag_name = f'{self._name.replace("/", "-")}_{verstr}'
        props = stamp_utils.VersionControlBackend.get_tag_properties(tag_name)

        should_append_hotfix = props["hotfix"] is not None
        if should_append_hotfix and self._hide_zero_hotfix:
            should_append_hotfix = props["hotfix"] != "0"

        if should_append_hotfix:
            props["version"] = f'{props["version"]}.{props["hotfix"]}'

        release_tag_name = f'{self._name.replace("/", "-")}_{props["version"]}'
        match = re.search(stamp_utils.VMN_TAG_REGEX, release_tag_name)
        if match is None:
            raise RuntimeError(
                f"Tag {release_tag_name} doesn't comply to vmn version format"
            )

        tag_name, tag_ver_info_form_repo = self.backend.get_vmn_tag_version_info(
            tag_name
        )
        ver_info = {
            "stamping": {
                "app": copy.deepcopy(tag_ver_info_form_repo["stamping"]["app"])
            }
        }
        ver_info["stamping"]["app"]["_version"] = props["version"]
        ver_info["stamping"]["app"]["prerelease"] = "release"

        messages = [
            yaml.dump(ver_info, sort_keys=True),
        ]

        self.backend.tag(
            [release_tag_name], messages, ref=self.backend.changeset(tag=tag_name)
        )

        return props["version"]

    def stamp_app_version(
        self,
        initial_version,
        initial_prerelease,
        initial_prerelease_count,
    ):
        for repo in self._flat_configured_deps:
            if repo in self.actual_deps_state:
                continue

            raise RuntimeError(
                "A dependency repository was specified in "
                "conf.yml file. However repo: {0} does not exist. "
                "Please clone and rerun".format(os.path.join(self.backend.root(), repo))
            )

        # TODO: verify that can be called multiple times with same result
        current_version, prerelease, prerelease_count = self.gen_app_version(
            initial_version,
            initial_prerelease,
            initial_prerelease_count,
        )

        VersionControlStamper.write_version_to_file(
            file_path=self._version_file_path,
            version_number=current_version,
            prerelease=prerelease,
            prerelease_count=prerelease_count,
        )

        info = {}
        if self._extra_info:
            info["env"] = dict(os.environ)

        release_mode = self._release_mode
        if prerelease is not None:
            release_mode = "prerelease"

        self.update_stamping_info(
            info,
            initial_version,
            initial_prerelease,
            initial_prerelease_count,
            current_version,
            prerelease,
            prerelease_count,
            release_mode,
        )

        return current_version, prerelease, prerelease_count

    def update_stamping_info(
        self,
        info,
        initial_version,
        initial_prerelease,
        initial_prerelease_count,
        current_version,
        prerelease,
        prerelease_count,
        release_mode,
    ):
        verstr = self.gen_verstr(current_version, prerelease, prerelease_count)
        self.current_version_info["stamping"]["app"]["_version"] = verstr
        self.current_version_info["stamping"]["app"]["prerelease"] = prerelease
        initial_verstr = self.gen_verstr(
            initial_version, initial_prerelease, initial_prerelease_count
        )
        self.current_version_info["stamping"]["app"][
            "previous_version"
        ] = initial_verstr
        self.current_version_info["stamping"]["app"]["release_mode"] = release_mode
        self.current_version_info["stamping"]["app"]["info"] = copy.deepcopy(info)
        self.current_version_info["stamping"]["app"][
            "stamped_on_branch"
        ] = self.backend.get_active_branch()
        self.current_version_info["stamping"]["app"][
            "prerelease_count"
        ] = copy.deepcopy(prerelease_count)

    def stamp_root_app_version(
        self,
        override_version=None,
    ):
        if self._root_app_name is None:
            return None

        if "version" not in self.ver_info_form_repo["stamping"]["root_app"]:
            raise RuntimeError(
                f"Root app name is {self._root_app_name} and app name is {self._name}. "
                f"However no version information for root was found"
            )

        old_version = self.ver_info_form_repo["stamping"]["root_app"]["version"]

        if override_version is None:
            override_version = old_version

        root_version = int(override_version) + 1

        with open(self._root_app_conf_path) as f:
            data = yaml.safe_load(f)
            # TODO: why do we need deepcopy here?
            external_services = copy.deepcopy(data["conf"]["external_services"])

        root_app = self.ver_info_form_repo["stamping"]["root_app"]
        services = copy.deepcopy(root_app["services"])

        self.current_version_info["stamping"]["root_app"].update(
            {
                "version": root_version,
                "services": services,
                "external_services": external_services,
            }
        )

        msg_root_app = self.current_version_info["stamping"]["root_app"]
        msg_app = self.current_version_info["stamping"]["app"]
        msg_root_app["services"][self._name] = msg_app["_version"]

        return "{0}".format(root_version)

    def get_files_to_add_to_index(self, paths):
        changed = [
            os.path.join(self._root_path, item.a_path.replace("/", os.sep))
            for item in self.backend._be.index.diff(None)
        ]
        untracked = [
            os.path.join(self._root_path, item.replace("/", os.sep))
            for item in self.backend._be.untracked_files
        ]

        version_files = []
        for path in paths:
            if path in changed or path in untracked:
                version_files.append(path)

        return version_files

    def publish_stamp(
        self, app_version, prerelease, prerelease_count, root_app_version
    ):
        if not self._should_publish:
            return 0

        version_files = self.get_files_to_add_to_index(
            [
                self._app_conf_path,
                self._version_file_path,
            ]
        )

        if self._root_app_name is not None:
            tmp = self.get_files_to_add_to_index([self._root_app_conf_path])
            if tmp:
                version_files.extend(tmp)

        verstr = self.gen_verstr(app_version, prerelease, prerelease_count)

        self.current_version_info["stamping"][
            "msg"
        ] = "{0}: Stamped version {1}\n\n".format(self._name, verstr)
        self.backend.commit(
            message=self.current_version_info["stamping"]["msg"],
            user="vmn",
            include=version_files,
        )

        app_msg = {
            "vmn_info": self.current_version_info["vmn_info"],
            "stamping": {"app": self.current_version_info["stamping"]["app"]},
        }

        tag = f'{self._name.replace("/", "-")}_{verstr}'
        match = re.search(stamp_utils.VMN_TAG_REGEX, tag)
        if match is None:
            LOGGER.error(
                f"Tag {tag} doesn't comply to vmn version format"
                f"Reverting vmn changes ..."
            )
            self.backend.revert_vmn_changes()

            return 3

        tags = [tag]
        msgs = [app_msg]

        if self._root_app_name is not None:
            root_app_msg = {
                "stamping": {
                    "root_app": self.current_version_info["stamping"]["root_app"]
                }
            }
            msgs.append(root_app_msg)
            tag = f"{self._root_app_name}_{root_app_version}"
            match = re.search(stamp_utils.VMN_ROOT_TAG_REGEX, tag)
            if match is None:
                LOGGER.error(
                    f"Tag {tag} doesn't comply to vmn version format"
                    f"Reverting vmn changes ..."
                )
                self.backend.revert_vmn_changes()

                return 3

            tags.append(tag)

        all_tags = []
        all_tags.extend(tags)

        try:
            for t, m in zip(tags, msgs):
                self.backend.tag([t], [yaml.dump(m, sort_keys=True)])
        except Exception as exc:
            LOGGER.debug("Logged Exception message:", exc_info=True)
            LOGGER.info(f"Reverting vmn changes for tags: {tags} ... ")
            self.backend.revert_vmn_changes(all_tags)

            return 1

        try:
            self.backend.push(all_tags)
        except Exception:
            LOGGER.debug("Logged Exception message:", exc_info=True)
            LOGGER.info(f"Reverting vmn changes for tags: {tags} ...")
            self.backend.revert_vmn_changes(all_tags)

            return 2

        return 0

    def retrieve_remote_changes(self):
        self.backend.pull()


def handle_init(vmn_ctx):
    be = vmn_ctx.vcs.backend

    path = os.path.join(vmn_ctx.params["root_path"], ".vmn", "vmn.init")
    if be.is_path_tracked(path):
        LOGGER.info("vmn tracking is already initialized")

        return 1

    # Backward compatability with vmn 0.3.9 code:
    file_path = backward_compatible_initialized_check(vmn_ctx.params)
    if file_path is not None and vmn_ctx.vcs.backend.is_path_tracked(file_path):
        LOGGER.info("vmn tracking is already initialized")

        return 1

    err = _safety_validation(vmn_ctx.vcs)
    if err:
        return 1

    changeset = be.changeset()

    vmn_path = os.path.join(vmn_ctx.params["root_path"], ".vmn")
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_init_path = os.path.join(vmn_path, "vmn.init")
    Path(vmn_init_path).touch()
    git_ignore_path = os.path.join(vmn_path, ".gitignore")

    with open(git_ignore_path, "w+") as f:
        for ignored_file in IGNORED_FILES:
            f.write(f"{ignored_file}{os.linesep}")

    be.commit(
        message=stamp_utils.INIT_COMMIT_MESSAGE,
        user="vmn",
        include=[vmn_init_path, git_ignore_path],
    )
    be.push()

    LOGGER.info(f'Initialized vmn tracking on {vmn_ctx.params["root_path"]}')

    return 0


def handle_init_app(vmn_ctx):
    # TODO: validate version number is of type major.minor.patch[.hotfix]
    err = _init_app(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    if err:
        return 1

    LOGGER.info(
        "Initialized app tracking on {0}".format(vmn_ctx.params["root_app_dir_path"])
    )

    return 0


def handle_stamp(vmn_ctx):
    if vmn_ctx.args.pull:
        vmn_ctx.vcs.retrieve_remote_changes()

    path = os.path.join(vmn_ctx.params["root_path"], ".vmn", "vmn.init")
    if not vmn_ctx.vcs.backend.is_path_tracked(path):
        # Backward compatability with vmn 0.3.9 code:
        file_path = backward_compatible_initialized_check(vmn_ctx.params)

        if file_path is None or not vmn_ctx.vcs.backend.is_path_tracked(file_path):
            LOGGER.error(
                "vmn tracking is not yet initialized. Run vmn init on the repository"
            )

            return 1

    if not vmn_ctx.vcs.tracked:
        LOGGER.error("Trying to stamp an untracked app. Run vmn init-app first")
        return 1

    (
        initial_version,
        prerelease,
        prerelease_count,
    ) = VersionControlStamper.get_version_number_from_file(
        vmn_ctx.vcs._version_file_path
    )

    matched_version_info = vmn_ctx.vcs.find_matching_version(
        initial_version,
        prerelease,
        prerelease_count,
    )
    if matched_version_info is not None:
        # Good we have found an existing version matching
        # the actual_deps_state

        version = vmn_ctx.vcs.get_be_formatted_version(
            matched_version_info["stamping"]["app"]["_version"]
        )

        LOGGER.info(version)

        return 0

    err = _safety_validation(vmn_ctx.vcs)
    if err:
        return 1

    try:
        version = _stamp_version(
            vmn_ctx.vcs,
            vmn_ctx.args.pull,
            initial_version,
            prerelease,
            prerelease_count,
        )
    except Exception as exc:
        LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    LOGGER.info(version)

    return 0


def handle_release(vmn_ctx):
    err = _safety_validation(vmn_ctx.vcs, allow_detached_head=True)
    if err:
        return 1

    try:
        LOGGER.info(vmn_ctx.vcs.release_app_version(vmn_ctx.args.version))
    except Exception as exc:
        LOGGER.error(f"Failed to release {vmn_ctx.args.version}")
        LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    return 0


def _handle_add(vmn_ctx):
    vmn_ctx.params["buildmetadata"] = vmn_ctx.args.build_metadata
    vmn_ctx.params["releasenotes"] = vmn_ctx.args.releasenotes
    version = vmn_ctx.args.version

    err = _safety_validation(vmn_ctx.vcs, allow_detached_head=True)
    if err:
        return 1

    try:
        raise NotImplementedError("Adding metadata to versions is not supported yet")
    except Exception as exc:
        LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    return 0


def handle_show(vmn_ctx):
    # root app does not have raw version number
    if vmn_ctx.params["root"]:
        vmn_ctx.params["raw"] = False
    else:
        vmn_ctx.params["raw"] = vmn_ctx.args.raw

    vmn_ctx.params["verbose"] = vmn_ctx.args.verbose
    vmn_ctx.params["cmdline_template"] = vmn_ctx.args.template

    err = _safety_validation(vmn_ctx.vcs, allow_detached_head=True)
    if err:
        return 1

    return show(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)


def handle_goto(vmn_ctx):
    vmn_ctx.params["deps_only"] = vmn_ctx.args.deps_only

    return goto_version(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)


def _safety_validation(versions_be_ifc, allow_detached_head=False):
    be = versions_be_ifc.backend

    err = be.check_for_git_user_config()
    # TODO: verify err from same type across all functions
    if err:
        LOGGER.info("{0}. Exiting".format(err))
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info("{0}. Exiting".format(err))
        return err

    if allow_detached_head:
        if be.in_detached_head():
            return err

    # TODO: think again about outgoing changes in detached head
    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info("{0}. Exiting".format(err))
        return err

    return err


def _init_app(versions_be_ifc, params, starting_version):
    path = os.path.join(params["root_path"], ".vmn", "vmn.init")
    if not versions_be_ifc.backend.is_path_tracked(path):
        # Backward compatability with vmn 0.3.9 code:
        file_path = backward_compatible_initialized_check(params)

        if file_path is None or not versions_be_ifc.backend.is_path_tracked(file_path):
            LOGGER.info("vmn tracking is not yet initialized")
            return 1

    err = _safety_validation(versions_be_ifc)
    if err:
        return 1

    if versions_be_ifc.tracked:
        LOGGER.info("Will not init an already tracked app")

        return 1

    versions_be_ifc.create_config_files(params)
    VersionControlStamper.write_version_to_file(
        file_path=versions_be_ifc._version_file_path,
        version_number=starting_version,
        prerelease="release",
        prerelease_count={},
    )

    info = {}
    versions_be_ifc.update_stamping_info(
        info,
        starting_version,
        "release",
        {},
        starting_version,
        "release",
        {},
        "init",
    )

    root_app_version = 0
    services = {}
    if versions_be_ifc._root_app_name is not None:
        with open(versions_be_ifc._root_app_conf_path) as f:
            data = yaml.safe_load(f)
            # TODO: why do we need deepcopy here?
            external_services = copy.deepcopy(data["conf"]["external_services"])

        ver_info = versions_be_ifc.backend.get_vmn_version_info(
            versions_be_ifc._root_app_name, root=True
        )
        if ver_info:
            root_app_version = int(ver_info["stamping"]["root_app"]["version"]) + 1
            root_app = ver_info["stamping"]["root_app"]
            services = copy.deepcopy(root_app["services"])

        versions_be_ifc.current_version_info["stamping"]["root_app"].update(
            {
                "version": root_app_version,
                "services": services,
                "external_services": external_services,
            }
        )

        msg_root_app = versions_be_ifc.current_version_info["stamping"]["root_app"]
        msg_app = versions_be_ifc.current_version_info["stamping"]["app"]
        msg_root_app["services"][versions_be_ifc._name] = msg_app["_version"]

    err = versions_be_ifc.publish_stamp(
        starting_version, "release", {}, root_app_version
    )
    if err:
        raise RuntimeError("Failed to init app")

    return 0


def backward_compatible_initialized_check(params):
    path = os.path.join(params["root_path"], ".vmn")
    file_path = None
    for f in os.listdir(path):
        if os.path.isfile(os.path.join(path, f)):
            if f not in IGNORED_FILES:
                file_path = os.path.join(path, f)
                break

    return file_path


def _stamp_version(
    versions_be_ifc, pull, initial_version, initial_prerelease, initial_prerelease_count
):
    # Here we one of the following:
    # tracked & not init only => normal stamp
    # not tracked & init only => only init a new app
    # not tracked & not init only => init and stamp a new app

    # We didn't find any existing version
    stamped = False
    retries = 3
    override_initial_version = initial_version
    override_initial_prerelease = initial_prerelease
    override_initial_prerelease_count = initial_prerelease_count
    override_main_current_version = None

    newer_stamping = version_mod.version != "dev" and (
        pversion.parse(versions_be_ifc.ver_info_form_repo["vmn_info"]["vmn_version"])
        > pversion.parse(version_mod.version)
    )
    if newer_stamping:
        raise RuntimeError("Refusing to stamp with old vmn. Please upgrade")

    if versions_be_ifc.bad_format_template:
        LOGGER.warning(versions_be_ifc.template_err_str)

    while retries:
        retries -= 1

        (
            current_version,
            prerelease,
            prerelease_count,
        ) = versions_be_ifc.stamp_app_version(
            override_initial_version,
            override_initial_prerelease,
            override_initial_prerelease_count,
        )
        main_ver = versions_be_ifc.stamp_root_app_version(
            override_main_current_version,
        )

        err = versions_be_ifc.publish_stamp(
            current_version, prerelease, prerelease_count, main_ver
        )
        if not err:
            stamped = True
            break

        if err == 1:
            override_initial_version = current_version
            override_initial_prerelease = prerelease
            override_initial_prerelease_count = prerelease_count
            override_main_current_version = main_ver

            LOGGER.warning(
                "Failed to publish. Trying to auto-increase "
                "from {0} to {1}".format(
                    current_version,
                    versions_be_ifc.gen_app_version(
                        override_initial_version,
                        override_initial_prerelease,
                        override_initial_prerelease_count,
                    )[0],
                )
            )
        elif err == 2:
            if not pull:
                break

            time.sleep(random.randint(1, 5))
            versions_be_ifc.retrieve_remote_changes()
        else:
            break

    if not stamped:
        raise RuntimeError("Failed to stamp")

    verstr = versions_be_ifc.gen_verstr(current_version, prerelease, prerelease_count)

    return versions_be_ifc.get_be_formatted_version(verstr)


def show(vcs, params, verstr=None):
    tag_name, ver_info = _retrieve_version_info(params, vcs, verstr)

    if ver_info is None:
        LOGGER.error("No such app: {0}".format(params["name"]))
        return 1

    if ver_info is None:
        LOGGER.error(
            "Version information was not found "
            "for {0}.".format(
                params["name"],
            )
        )

        return 1

    # TODO: refactor
    if params["root"]:
        data = ver_info["stamping"]["root_app"]
        if not data:
            LOGGER.error(
                "App {0} does not have a root app ".format(
                    params["name"],
                )
            )

            return 1

        if params.get("verbose"):
            yaml.dump(data, sys.stdout)
        else:
            print(data["version"])

        return 0

    data = ver_info["stamping"]["app"]
    data["version"] = stamp_utils.VersionControlBackend.get_utemplate_formatted_version(
        data["_version"], vcs.template, vcs._hide_zero_hotfix
    )
    if params.get("verbose"):
        yaml.dump(data, sys.stdout)
    elif params.get("raw"):
        print(data["_version"])
    else:
        print(data["version"])

    return 0


def goto_version(vcs, params, version):
    tag_name, ver_info = _retrieve_version_info(params, vcs, version)

    if ver_info is None:
        LOGGER.error("No such app: {0}".format(params["name"]))
        return 1

    data = ver_info["stamping"]["app"]
    deps = data["changesets"]
    deps.pop(".")
    if deps:
        if version is None:
            for rel_path, v in deps.items():
                v["hash"] = None

        _goto_version(deps, params["root_path"])

    if version is None and not params["deps_only"]:
        vcs.backend.checkout_branch()
    elif not params["deps_only"]:
        try:
            vcs.backend.checkout(tag=tag_name)
        except Exception:
            LOGGER.error(
                "App: {0} with version: {1} was "
                "not found".format(params["name"], version)
            )

            return 1

    return 0


def _retrieve_version_info(params, vcs, verstr):
    path = os.path.join(params["root_path"], ".vmn", "vmn.init")
    if not vcs.backend.is_path_tracked(path):
        # Backward compatability with vmn 0.3.9 code:
        file_path = backward_compatible_initialized_check(params)

        if file_path is None or not vcs.backend.is_path_tracked(file_path):
            LOGGER.info("vmn tracking is not yet initialized")

            return None, None

    err = _safety_validation(vcs, allow_detached_head=True)
    if err:
        return None, None

    tag_name = f'{params["name"].replace("/", "-")}'
    if verstr is not None:
        tag_name = f"{tag_name}_{verstr}"

    if verstr is None:
        try:
            ver_info = vcs.backend.get_vmn_version_info(
                params["name"],
                params["root"],
            )
        except:
            return None, None
    else:
        if params["root"]:
            try:
                int(verstr)
                tag_name, ver_info = vcs.backend.get_vmn_tag_version_info(tag_name)
            except Exception:
                LOGGER.error("wrong version specified: root version must be an integer")

                return None, None
        else:
            try:
                stamp_utils.VersionControlBackend.get_tag_properties(tag_name)
                tag_name, ver_info = vcs.backend.get_vmn_tag_version_info(tag_name)
            except:
                LOGGER.error(f"Wrong version specified: {verstr}")

                return None, None

    if ver_info is None:
        return None, None

    return tag_name, ver_info


def _update_repo(args):
    path, rel_path, changeset = args

    client = None
    try:
        client, err = stamp_utils.get_client(path)
        if client is None:
            return {"repo": rel_path, "status": 0, "description": err}
    except Exception as exc:
        LOGGER.exception(
            "Unexpected behaviour:\nAborting update " f"operation in {path} Reason:\n"
        )

        return {"repo": rel_path, "status": 1, "description": None}

    try:
        err = client.check_for_pending_changes()
        if err:
            LOGGER.info("{0}. Aborting update operation ".format(err))
            return {"repo": rel_path, "status": 1, "description": err}

    except Exception as exc:
        LOGGER.debug(f'Skipping "{path}"')
        LOGGER.debug("Exception info: ", exc_info=True)

        return {"repo": rel_path, "status": 0, "description": None}

    try:
        if not client.in_detached_head():
            err = client.check_for_outgoing_changes()
            if err:
                LOGGER.info("{0}. Aborting update operation".format(err))
                return {"repo": rel_path, "status": 1, "description": err}

        LOGGER.info("Updating {0}".format(rel_path))
        if changeset is None:
            if not client.in_detached_head():
                client.pull()

            rev = client.checkout_branch()

            LOGGER.info("Updated {0} to {1}".format(rel_path, rev))
        else:
            cur_changeset = client.changeset()
            if not client.in_detached_head():
                client.pull()

            client.checkout(rev=changeset)

            LOGGER.info("Updated {0} to {1}".format(rel_path, changeset))
    except Exception as exc:
        LOGGER.exception(
            f"Unexpected behaviour:\nAborting update operation in {path} " "Reason:\n"
        )

        try:
            client.checkout(rev=cur_changeset)
        except Exception:
            LOGGER.exception("Unexpected behaviour:")

        return {"repo": rel_path, "status": 1, "description": None}

    return {"repo": rel_path, "status": 0, "description": None}


def _clone_repo(args):
    path, rel_path, remote, vcs_type = args
    if os.path.exists(path):
        return {"repo": rel_path, "status": 0, "description": None}

    LOGGER.info("Cloning {0}..".format(rel_path))
    try:
        if vcs_type == "git":
            stamp_utils.GitBackend.clone(path, remote)
    except Exception as exc:
        try:
            str = "already exists and is not an empty directory."
            if str in exc.stderr:
                return {"repo": rel_path, "status": 0, "description": None}
        except Exception:
            pass

        err = "Failed to clone {0} repository. " "Description: {1}".format(
            rel_path, exc.args
        )
        return {"repo": rel_path, "status": 1, "description": err}

    return {"repo": rel_path, "status": 0, "description": None}


def _goto_version(deps, root):
    args = []
    for rel_path, v in deps.items():
        if v["remote"].startswith("."):
            v["remote"] = os.path.join(root, v["remote"])
        args.append(
            (os.path.join(root, rel_path), rel_path, v["remote"], v["vcs_type"])
        )
    with Pool(min(len(args), 10)) as p:
        results = p.map(_clone_repo, args)

    for res in results:
        if res["status"] == 1:
            if res["repo"] is None and res["description"] is None:
                continue

            msg = "Failed to clone "
            if res["repo"] is not None:
                msg += "from {0} ".format(res["repo"])
            if res["description"] is not None:
                msg += "because {0}".format(res["description"])

            LOGGER.info(msg)

    args = []
    for rel_path, v in deps.items():
        args.append((os.path.join(root, rel_path), rel_path, v["hash"]))

    with Pool(min(len(args), 20)) as p:
        results = p.map(_update_repo, args)

    err = False
    for res in results:
        if res["status"] == 1:
            err = True
            if res["repo"] is None and res["description"] is None:
                continue

            msg = "Failed to update "
            if res["repo"] is not None:
                msg += " {0} ".format(res["repo"])
            if res["description"] is not None:
                msg += "because {0}".format(res["description"])

            LOGGER.warning(msg)

    if err:
        raise RuntimeError(
            "Failed to update one or more " "of the required repos. See log above"
        )


def build_world(name, working_dir, root_context, release_mode, prerelease):
    params = {
        "name": name,
        "working_dir": working_dir,
        "root": root_context,
        "release_mode": release_mode,
        "prerelease": prerelease,
        "buildmetadata": None,
    }

    # TODO: think how vcs can be used here
    be, err = stamp_utils.get_client(params["working_dir"])
    if err:
        LOGGER.error("{0}. Exiting".format(err))
        return None

    root_path = os.path.join(be.root())
    params["root_path"] = root_path

    if name is None:
        return params

    app_dir_path = os.path.join(
        root_path,
        ".vmn",
        params["name"].replace("/", os.sep),
    )
    params["app_dir_path"] = app_dir_path

    params["version_file_path"] = os.path.join(app_dir_path, VER_FILE_NAME)

    app_conf_path = os.path.join(app_dir_path, "conf.yml")
    params["app_conf_path"] = app_conf_path
    params["repo_name"] = os.path.basename(root_path)

    if root_context:
        root_app_name = name
    else:
        root_app_name = params["name"].split("/")
        if len(root_app_name) == 1:
            root_app_name = None
        else:
            root_app_name = "/".join(root_app_name[:-1])

    params["root_app_dir_path"] = app_dir_path
    root_app_conf_path = None
    if root_app_name is not None:
        root_app_dir_path = os.path.join(
            root_path,
            ".vmn",
            root_app_name,
        )

        params["root_app_dir_path"] = root_app_dir_path
        root_app_conf_path = os.path.join(root_app_dir_path, "root_conf.yml")

    params["root_app_conf_path"] = root_app_conf_path
    params["root_app_name"] = root_app_name

    params["raw_configured_deps"] = {
        os.path.join("../"): {
            os.path.basename(root_path): {"remote": be.remote(), "vcs_type": be.type()}
        }
    }

    params["template"] = stamp_utils.VMN_DEFAULT_TEMPLATE

    params["extra_info"] = False
    # TODO: handle redundant parse template here

    deps = {}
    for rel_path, dep in params["raw_configured_deps"].items():
        deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

    actual_deps_state = HostState.get_actual_deps_state(deps, root_path)
    actual_deps_state["."]["hash"] = be.last_user_changeset()
    params["actual_deps_state"] = actual_deps_state
    params["hide_zero_hotfix"] = True

    if not os.path.isfile(app_conf_path):
        return params

    with open(app_conf_path, "r") as f:
        data = yaml.safe_load(f)
        params["template"] = data["conf"]["template"]
        params["extra_info"] = data["conf"]["extra_info"]
        params["raw_configured_deps"] = data["conf"]["deps"]
        if "hide_zero_hotfix" in data["conf"]:
            params["hide_zero_hotfix"] = data["conf"]["hide_zero_hotfix"]

        deps = {}
        for rel_path, dep in params["raw_configured_deps"].items():
            deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

        actual_deps_state.update(HostState.get_actual_deps_state(deps, root_path))
        params["actual_deps_state"] = actual_deps_state
        actual_deps_state["."]["hash"] = be.last_user_changeset()

    if "cmdline_template" in params:
        params["template"] = params["cmdline_template"]

    return params


def main(command_line=None):
    return vmn_run(command_line)


def vmn_run(command_line):
    with VMNContextMAnagerManager(command_line) as vmn_ctx:
        if vmn_ctx.args.command == "init":
            err = handle_init(vmn_ctx)
        elif vmn_ctx.args.command == "init-app":
            err = handle_init_app(vmn_ctx)
        elif vmn_ctx.args.command == "show":
            err = handle_show(vmn_ctx)
        elif vmn_ctx.args.command == "stamp":
            err = handle_stamp(vmn_ctx)
        elif vmn_ctx.args.command == "goto":
            err = handle_goto(vmn_ctx)
        elif vmn_ctx.args.command == "release":
            err = handle_release(vmn_ctx)
        else:
            LOGGER.info("Run vmn -h for help")
            err = 0

    return err


def validate_app_name(args):
    if args.name.startswith("/"):
        raise RuntimeError("App name cannot start with {0}".format("/"))
    if "-" in args.name:
        raise RuntimeError("App name cannot contain {0}".format("-"))


def parse_user_commands(command_line):
    parser = argparse.ArgumentParser("vmn")
    parser.add_argument(
        "--version", "-v", action="version", version=version_mod.version
    )
    parser.add_argument("--debug", required=False, action="store_true")
    parser.set_defaults(debug=False)
    subprasers = parser.add_subparsers(dest="command")
    subprasers.add_parser(
        "init",
        help="initialize version tracking for the repository. "
        "This command should be called only once per repository",
    )
    pinitapp = subprasers.add_parser(
        "init-app",
        help="initialize version tracking for application. "
        "This command should be called only once per application",
    )
    pinitapp.add_argument(
        "-v",
        "--version",
        default="0.0.0",
        help="The version to init from. Must be specified in the raw version format: "
        "{major}.{minor}.{patch}",
    )
    pinitapp.add_argument(
        "name", help="The application's name to initialize version tracking for"
    )
    pshow = subprasers.add_parser("show", help="show app version")
    pshow.add_argument("name", help="The application's name to show the version for")
    pshow.add_argument(
        "-v",
        "--version",
        default=None,
        help=f"The version to show. Must be specified in the raw version format:"
        f" {stamp_utils.VMN_VERSION_FORMAT}",
    )
    pshow.add_argument(
        "-t", "--template", default=None, help="The template to use in show"
    )
    pshow.add_argument("--root", dest="root", action="store_true")
    pshow.set_defaults(root=False)
    pshow.add_argument("--verbose", dest="verbose", action="store_true")
    pshow.set_defaults(verbose=False)
    pshow.add_argument("--raw", dest="raw", action="store_true")
    pshow.set_defaults(raw=False)
    pstamp = subprasers.add_parser("stamp", help="stamp version")
    pstamp.add_argument(
        "-r",
        "--release-mode",
        choices=["major", "minor", "patch", "hotfix", "micro"],
        default=None,
        help="major / minor / patch / hotfix",
    )
    pstamp.add_argument(
        "--pr",
        "--prerelease",
        default=None,
        help="Prerelease version. Can be anything really until you decide "
        "to release the version",
    )
    pstamp.add_argument("--pull", dest="pull", action="store_true")
    pstamp.set_defaults(pull=False)
    pstamp.add_argument("name", help="The application's name")
    pgoto = subprasers.add_parser("goto", help="go to version")
    pgoto.add_argument(
        "-v",
        "--version",
        default=None,
        required=False,
        help=f"The version to go to in the format: "
        f" {stamp_utils.VMN_VERSION_FORMAT}",
    )
    pgoto.add_argument("--root", dest="root", action="store_true")
    pgoto.set_defaults(root=False)
    pgoto.add_argument("--deps-only", dest="deps_only", action="store_true")
    pgoto.set_defaults(deps_only=False)
    pgoto.add_argument("name", help="The application's name")
    prelease = subprasers.add_parser("release", help="Release app version")
    prelease.add_argument(
        "-v",
        "--version",
        required=True,
        help=f"The version to release in the format: "
        f" {stamp_utils.VMN_VERSION_FORMAT}",
    )
    prelease.add_argument("name", help="The application's name")
    padd = subprasers.add_parser("add", help="add attributes to existing app version")
    padd.add_argument(
        "-t",
        "--type",
        choices=["build", "releasenotes"],
        required=True,
        help="build / releasenotes",
    )
    padd.add_argument(
        "-v",
        "--version",
        required=True,
        help=f"The version to add to in the format: "
        f" {stamp_utils.VMN_VERSION_FORMAT}",
    )
    padd.add_argument("name", help="The application's name")
    args = parser.parse_args(command_line)

    return args


if __name__ == "__main__":
    err = main()
    if err:
        sys.exit(1)

    sys.exit(0)
