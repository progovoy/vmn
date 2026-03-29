#!/usr/bin/env python3
"""IVersionsStamper — base class for version operations."""
import copy
import json
import os
import pathlib
import re
import shutil
from dataclasses import fields
from pathlib import Path

import jinja2
import tomlkit
import yaml

from version_stamp import version as version_mod
from version_stamp.backends.base import VMNBackend
from version_stamp.backends.factory import get_client
from version_stamp.core.constants import (
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    SUPPORTED_REGEX_VARS,
    VMN_OLD_TEMPLATE,
    VMN_TEMPLATE_REGEX,
    VMN_VERSION_FORMAT,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.models import AppConf, VMN_DEFAULT_CONF
from version_stamp.core.utils import comment_out_jinja
from version_stamp.stamping.template_data import (
    create_data_dict_for_jinja2,
    gen_jinja2_template_from_data,
)

VER_FILE_NAME = "last_known_app_version.yml"


class IVersionsStamper(object):
    _STRUCTURED_BACKEND_SPEC = {
        "npm":    {"format": "json", "key_path": ["version"]},
        "cargo":  {"format": "toml", "key_path": ["package", "version"]},
        "poetry": {"format": "toml", "key_path": ["tool", "poetry", "version"]},
        "pep621": {"format": "toml", "key_path": ["project", "version"]},
    }

    @measure_runtime_decorator
    def __init__(self, arg_params):
        # actual value will be assigned on handle_ functions
        self.actual_deps_state = None
        self.last_user_changeset = None
        self.prerelease = None
        self.release_mode = None
        self.dry_run = None

        self.app_conf_path = None
        self.params: dict = arg_params
        self.vmn_root_path: str = arg_params["root_path"]
        self.repo_name: str = "."
        self.name: str = arg_params["name"]
        self.be_type = arg_params["be_type"]

        # Configuration defaults — AppConf is the single source of truth.
        # Individual attributes remain on self for backward compatibility
        # (tests and external code access self.__dict__).
        _defaults = AppConf()
        _key_to_attr = AppConf.conf_key_to_attr()
        for _f in fields(AppConf):
            setattr(self, _key_to_attr[_f.name], getattr(_defaults, _f.name))

        self.configured_deps = {}
        self.conf_file_exists = False
        self.root_conf_file_exists = False

        self.should_publish = True
        self.current_version_info = {
            "vmn_info": {
                "description_message_version": "1.1",
                "vmn_version": version_mod.version,
            },
            "stamping": {"msg": "", "app": {"info": {}}, "root_app": {}},
        }

        # root_context means that the user uses vmn in a context of a root app
        self.root_context = arg_params["root"]

        self.backend, err = get_client(
            self.vmn_root_path,
            self.be_type,
            inherit_env=True,
        )
        if err:
            err_str = "Failed to create backend {0}. Exiting".format(err)
            VMN_LOGGER.error(err_str)
            raise RuntimeError(err_str)

        if self.name is None:
            self.tracked = False
            return

        self.initialize_paths()
        self.update_attrs_from_app_conf_file()

        self.version_files = [self.app_conf_path, self.version_file_path]

        if not self.root_context:
            self.current_version_info["stamping"]["app"]["name"] = self.name

        if self.root_app_name is not None:
            self.current_version_info["stamping"]["root_app"] = {
                "name": self.root_app_name,
                # if we stamp, the latest service will be the self.name indeed.
                # when we show, we want to show self.name service as latest
                "latest_service": self.name,
                "services": {},
                "external_services": self.external_services,
            }

        err = self.initialize_backend_attrs()
        if err:
            # TODO:: test this
            raise RuntimeError("Failed to initialize_backend_attrs")

    # Derived from AppConf field metadata — no manual sync needed.
    _CONF_KEY_TO_ATTR = AppConf.conf_key_to_attr()

    def update_attrs_from_app_conf_file(self):
        # TODO:: handle deleted app with missing conf file
        if os.path.isfile(self.app_conf_path):
            self.conf_file_exists = True

            with open(self.app_conf_path, "r") as f:
                data = yaml.safe_load(f)
                if "conf" in data:
                    if "template" in data["conf"]:
                        self.template = data["conf"]["template"]

                        if (
                            VMN_OLD_TEMPLATE
                            == self.template
                        ):
                            # TODO:: this means that using the old
                            #  default template format is impossible. I am okay with this for now.
                            VMN_LOGGER.warning(
                                "Identified old default template format. "
                                "will ignore and use the new default format"
                            )
                            self.template = VMN_DEFAULT_CONF["template"]
                    for conf_key, attr_name in self._CONF_KEY_TO_ATTR.items():
                        if conf_key == "template":
                            continue  # handled above with old-template detection
                        if conf_key in data["conf"]:
                            setattr(self, attr_name, data["conf"][conf_key])

                    cc = data["conf"].get("conventional_commits")
                    if (
                        isinstance(cc, dict)
                        and "default_release_mode" in cc
                    ):
                        raise RuntimeError(
                            "Detected 'default_release_mode' nested inside "
                            "'conventional_commits' in your conf.yml. "
                            "This is no longer supported. Please move it to "
                            "a top-level key:\n\n"
                            "  conf:\n"
                            "    default_release_mode: optional\n"
                            "    conventional_commits: {}\n"
                        )

                self.set_template(self.template)

        if self.root_app_conf_path is not None and os.path.isfile(
            self.root_app_conf_path
        ):
            self.root_conf_file_exists = True
            with open(self.root_app_conf_path) as f:
                data = yaml.safe_load(f)
                if "external_services" in data["conf"]:
                    self.external_services = data["conf"]["external_services"]

    def initialize_paths(self):
        self.app_dir_path = os.path.join(
            self.vmn_root_path, ".vmn", self.name.replace("/", os.sep)
        )

        self.version_file_path = os.path.join(self.app_dir_path, VER_FILE_NAME)

        self.app_conf_path = os.path.join(
            self.app_dir_path,
            f"{self.backend.active_branch}_conf.yml",
        )
        if not os.path.isfile(self.app_conf_path):
            self.app_conf_path = os.path.join(self.app_dir_path, "conf.yml")

        if self.root_context:
            self.root_app_name = self.name
        else:
            self.root_app_name = VMNBackend.get_root_app_name_from_name(
                self.name
            )

        self.external_services = None
        self.root_app_dir_path = self.app_dir_path
        self.root_app_conf_path = None
        if self.root_app_name is not None:
            self.root_app_dir_path = os.path.join(
                self.vmn_root_path, ".vmn", self.root_app_name
            )

            self.root_app_conf_path = os.path.join(
                self.root_app_dir_path,
                f"{self.backend.active_branch}_root_conf.yml",
            )
            if not os.path.isfile(self.root_app_conf_path):
                self.root_app_conf_path = os.path.join(
                    self.root_app_dir_path, "root_conf.yml"
                )

    def initialize_configured_deps(self, self_base, self_dep):
        if self.raw_configured_deps:
            self.configured_deps = self.raw_configured_deps

        if os.path.join("../") not in self.configured_deps:
            self.configured_deps[os.path.join("../")] = {}
        if self_base not in self.configured_deps[os.path.join("../")]:
            self.configured_deps[os.path.join("../")][self_base] = {}

        self.configured_deps[os.path.join("../")][self_base] = self_dep

        flat_deps = {}
        for rel_path, v in self.configured_deps.items():
            for repo in v:
                key = os.path.relpath(
                    os.path.join(self.vmn_root_path, rel_path, repo),
                    self.vmn_root_path,
                )
                flat_deps[key] = v[repo]

        self.configured_deps = flat_deps

    @measure_runtime_decorator
    def get_version_number_from_file(self) -> tuple:
        if not os.path.exists(self.version_file_path):
            return None, None

        with open(self.version_file_path, "r") as fid:
            ver_dict = yaml.safe_load(fid)
            if "version_to_stamp_from" in ver_dict:
                verstr = ver_dict["version_to_stamp_from"]
                # 0.8.4
                if "prerelease" in ver_dict:
                    base_verstr = verstr
                    prerelease = None
                    if ver_dict["prerelease"] != "release":
                        prerelease = f"{ver_dict['prerelease']}{ver_dict['prerelease_count'][ver_dict['prerelease']]}"
                    verstr = VMNBackend.serialize_vmn_version(
                        base_verstr,
                        prerelease=prerelease,
                        hide_zero_hotfix=self.hide_zero_hotfix,
                    )
            else:
                verstr = ver_dict["last_stamped_version"]

            try:
                props = VMNBackend.deserialize_vmn_version(verstr)
            except Exception:
                err = (
                    f"Version in version file: {verstr} doesn't comply with: "
                    f"{VMN_VERSION_FORMAT} format"
                )
                VMN_LOGGER.error(err)

                raise RuntimeError(err)

            return verstr, props

    @measure_runtime_decorator
    def get_first_reachable_version_info(
        self, app_name, root_context=False, type=RELATIVE_TO_GLOBAL_TYPE
    ):
        app_tags, cobj, ver_infos = self.backend.get_latest_stamp_tags(
            app_name, root_context, type
        )

        cleaned_app_tag = None
        for tag in app_tags:
            # skip buildmetadata versions
            if "+" in tag:
                continue

            props = VMNBackend.deserialize_tag_name(tag)

            # can happen in case of a root app
            if props.app_name != app_name:
                continue

            cleaned_app_tag = tag
            break

        if cleaned_app_tag is None:
            return None, {}

        if cleaned_app_tag not in ver_infos:
            VMN_LOGGER.debug(f"Somehow {cleaned_app_tag} not in ver_infos")
            return None, {}

        self.enhance_ver_info(ver_infos)

        return cleaned_app_tag, ver_infos

    @measure_runtime_decorator
    def enhance_ver_info(self, ver_infos):
        root_tag = None
        ver_tag = None
        for tag, ver_info_c in ver_infos.items():
            props = VMNBackend.deserialize_vmn_tag_name(tag)
            if "buildmetadata" in props.types:
                continue

            if "root" in props.types:
                root_tag = tag
                continue

            if props.types == {"version"}:
                ver_tag = tag
                continue

            if "prerelease" in props.types and ver_tag is None:
                continue

            # TODO:: Check API commit version

        if root_tag is None or ver_tag is None:
            return

        ver_infos[ver_tag]["ver_info"]["stamping"]["root_app"] = ver_infos[root_tag][
            "ver_info"
        ]["stamping"]["root_app"]

        ver_infos[root_tag]["ver_info"]["stamping"]["app"] = ver_infos[ver_tag][
            "ver_info"
        ]["stamping"]["app"]

    @measure_runtime_decorator
    def get_version_info_from_verstr(self, verstr):
        actual_tag = self.get_tag_name(verstr)

        try:
            VMNBackend.deserialize_vmn_version(verstr)
        except Exception:
            VMN_LOGGER.debug(exc_info=True)
            return actual_tag, {}

        actual_tag, ver_infos = self.backend.get_tag_version_info(actual_tag)
        if not ver_infos:
            VMN_LOGGER.error(
                f"Failed to get version info for tag: {actual_tag}"
            )

            return actual_tag, {}

        if actual_tag not in ver_infos or ver_infos[actual_tag]["ver_info"] is None:
            return actual_tag, {}

        self.enhance_ver_info(ver_infos)

        return actual_tag, ver_infos

    def get_tag_name(self, verstr):
        tag_name = f'{self.name.replace("/", "-")}'
        assert verstr is not None
        tag_name = f"{tag_name}_{verstr}"

        return tag_name

    @measure_runtime_decorator
    def initialize_backend_attrs(self):
        self_base = os.path.basename(self.vmn_root_path)
        self_dep = {"remote": self.backend.remote(), "vcs_type": self.backend.type()}

        self.initialize_configured_deps(self_base, self_dep)

        if self.name is None:
            return

        version_files_to_track_diff = []
        for backend in self.version_backends:
            try:
                backend_conf = self.version_backends[backend]
                if backend in self._STRUCTURED_BACKEND_SPEC:
                    self._add_files_simple_backend(version_files_to_track_diff, backend_conf)
                else:
                    handler = getattr(self, f"_add_files_{backend}")
                    handler(version_files_to_track_diff, backend_conf)
            except AttributeError:
                VMN_LOGGER.warning(f"Unsupported version backend {backend}")
                continue

        version_files_to_track_diff = list(dict.fromkeys(version_files_to_track_diff))

        self.last_user_changeset = self.backend.get_last_user_changeset(
            version_files_to_track_diff,
            self.name
        )
        if self.last_user_changeset is None:
            raise RuntimeError(
                "Somehow vmn was not able to get last user changeset. "
                "This usually means that not enough git commit history was cloned. "
                "This can happen when using shallow repositories. "
                "Check your clone / checkout process."
            )

        self.actual_deps_state = self.backend.get_actual_deps_state(
            self.vmn_root_path,
            self.configured_deps,
        )
        self.actual_deps_state["."]["hash"] = self.last_user_changeset
        self.current_version_info["stamping"]["app"]["changesets"] = copy.deepcopy(
            self.actual_deps_state
        )

        self.ver_infos_from_repo = {}
        self.selected_tag = None
        (
            self.verstr_from_file,
            self.props_from_file,
        ) = self.get_version_number_from_file()

        # verstr_from_file will be None only when running
        # for the first time or file removed somehow
        if self.verstr_from_file is not None:
            (
                self.selected_tag,
                self.ver_infos_from_repo,
            ) = self.get_version_info_from_verstr(self.verstr_from_file)
            base_ver = VMNBackend.get_base_vmn_version(
                self.verstr_from_file,
                self.hide_zero_hotfix,
            )
            t = self.get_tag_name(base_ver)
            if t != self.selected_tag and t in self.ver_infos_from_repo:
                self.selected_tag = t

        if not self.ver_infos_from_repo:
            (
                selected_tag,
                self.ver_infos_from_repo,
            ) = self.get_first_reachable_version_info(
                self.name,
                self.root_context,
                type=RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
            )

            self.enhance_ver_info(self.ver_infos_from_repo)

            if selected_tag is not None and selected_tag != self.selected_tag:
                self.selected_tag = selected_tag

        self.tracked = (
            self.selected_tag in self.ver_infos_from_repo
            and self.ver_infos_from_repo[self.selected_tag]["ver_info"] is not None
        )
        if self.tracked:
            for rel_path, dep in self.configured_deps.items():
                if rel_path.endswith(os.path.join("/", self_base)):
                    continue

                if "remote" in dep:
                    continue

                if rel_path in self.actual_deps_state:
                    dep["remote"] = self.actual_deps_state[rel_path]["remote"]
                elif (
                    rel_path
                    in self.ver_infos_from_repo[self.selected_tag]["ver_info"][
                        "stamping"
                    ]["app"]["changesets"]
                ):
                    dep["remote"] = self.ver_infos_from_repo[self.selected_tag][
                        "ver_info"
                    ]["stamping"]["app"]["changesets"][rel_path]["remote"]

        return 0

    def set_template(self, template):
        try:
            self.template = IVersionsStamper.parse_template(template)
            self.template_err_str = None
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            self.template = IVersionsStamper.parse_template(
                VMN_DEFAULT_CONF["template"]
            )
            self.template_err_str = (
                "Failed to parse template: "
                f"{template}. "
                f"Falling back to default one: "
                f"{VMN_DEFAULT_CONF['template']}"
            )

    def __del__(self):
        if hasattr(self, 'backend') and self.backend is not None:
            del self.backend
            self.backend = None

    # Note: this function generates a version (including prerelease)
    def gen_advanced_version(self, verstr):
        verstr, prerelease_count = self.advance_version(verstr, self.release_mode)

        return verstr, prerelease_count

    def increase_octet(
        self,
        tag_name_prefix: str,
        version_number_oct: int,
        release_mode: str,
        globally: bool,
    ) -> int:
        tag = self.backend.get_latest_available_tag(tag_name_prefix)
        if tag and globally:
            props = VMNBackend.deserialize_vmn_tag_name(tag)
            version_number_oct = max(version_number_oct, int(getattr(props, release_mode)))
        version_number_oct += 1

        return version_number_oct

    def advance_version(self, version, release_mode, globally=True):
        # Globally should only be used for the base version components.
        # prerelease should always be determined globally.
        # I do not see a use case in which I would like to get the counter
        # relatively to a branch for prerelease and not globally

        props = VMNBackend.deserialize_vmn_version(version)

        major = props.major
        minor = props.minor
        patch = props.patch
        hotfix = props.hotfix

        if release_mode == "major":
            tag_name_prefix = VMNBackend.app_name_to_tag_name(self.name)

            tag_name_prefix = f"{tag_name_prefix}_*"
            major = self.increase_octet(tag_name_prefix, major, release_mode, globally)

            minor = 0
            patch = 0
            hotfix = 0
        elif release_mode == "minor":
            tag_name_prefix = VMNBackend.app_name_to_tag_name(self.name)

            # TODO:: use serialize functions here
            tag_name_prefix = f"{tag_name_prefix}_{major}.*"
            minor = self.increase_octet(tag_name_prefix, minor, release_mode, globally)

            patch = 0
            hotfix = 0
        elif release_mode == "patch":
            tag_name_prefix = VMNBackend.app_name_to_tag_name(self.name)

            tag_name_prefix = f"{tag_name_prefix}_{major}.{minor}.*"
            patch = self.increase_octet(tag_name_prefix, patch, release_mode, globally)

            hotfix = 0
        elif release_mode == "hotfix":
            tag_name_prefix = VMNBackend.app_name_to_tag_name(self.name)

            tag_name_prefix = f"{tag_name_prefix}_{major}.{minor}.{patch}.*"
            hotfix = self.increase_octet(
                tag_name_prefix, hotfix, release_mode, globally
            )

        base_version = VMNBackend.serialize_vmn_base_version(
            major,
            minor,
            patch,
            hotfix,
            hide_zero_hotfix=self.hide_zero_hotfix,
        )

        initialprerelease = props.prerelease
        prerelease = self.prerelease
        # If user did not specify a change in prerelease,
        # stay with the previous one
        if prerelease is None:
            prerelease = initialprerelease
            if release_mode is not None:
                prerelease = "release"

        if prerelease == "release":
            return (
                VMNBackend.serialize_vmn_version(
                    base_version,
                    hide_zero_hotfix=self.hide_zero_hotfix,
                ),
                {},
            )

        initialprerelease_count = {}
        tag_name_prefix = VMNBackend.serialize_vmn_tag_name(
            self.name, base_version
        )
        tag_name_prefix = f"{tag_name_prefix}-*"
        tag = self.backend.get_latest_available_tag(tag_name_prefix)

        # Means we found existing prerelease
        if tag is not None:
            t, prerelease_ver_info_c = self.backend.parse_tag_message(tag)

            initialprerelease_count = prerelease_ver_info_c["ver_info"]["stamping"][
                "app"
            ]["prerelease_count"]

        if props.rcn is None:
            props.rcn = 0

        rcn = 0
        if prerelease == props.prerelease:
            rcn = props.rcn

        prerelease_count = initialprerelease_count
        if prerelease not in prerelease_count:
            prerelease_count[prerelease] = rcn

        prerelease_count[prerelease] = max(
            prerelease_count[prerelease],
            rcn,
        )

        prerelease_count[prerelease] += 1

        if release_mode is not None:
            prerelease_count = {prerelease: 1}

        return (
            VMNBackend.serialize_vmn_version(
                base_version,
                prerelease=prerelease,
                rcn=prerelease_count[prerelease],
                hide_zero_hotfix=self.hide_zero_hotfix,
            ),
            prerelease_count,
        )

    def write_version_to_file(self, version_number: str) -> None:
        if self.dry_run:
            VMN_LOGGER.info(
                "Would have written to version file:\n" f"version: {version_number}\n"
            )
        else:
            self._write_version_to_vmn_version_file(version_number)

        if not self.version_backends:
            return

        for backend in self.version_backends:
            try:
                if backend == "vmn_version_file":
                    VMN_LOGGER.warning(
                        "Remove vmn_version_file version backend from the configuration"
                    )
                    continue

                backend_conf = self.version_backends[backend]
                if backend in self._STRUCTURED_BACKEND_SPEC:
                    self._write_version_to_structured(version_number, backend_conf, backend)
                else:
                    handler = getattr(self, f"_write_version_to_{backend}")
                    handler(version_number, backend_conf)
            except AttributeError:
                VMN_LOGGER.warning(f"Unsupported version backend {backend}")
                continue

    def _write_version_to_structured(self, verstr, backend_conf, backend_name):
        spec = self._STRUCTURED_BACKEND_SPEC[backend_name]

        if self.dry_run:
            VMN_LOGGER.info(
                "Would have written to a version backend file:\n"
                f"backend: {backend_name}\n"
                f"version: {verstr}"
            )

            return

        file_path = os.path.join(self.vmn_root_path, backend_conf["path"])
        try:
            with open(file_path, "r") as f:
                if spec["format"] == "json":
                    data = json.load(f)
                else:
                    data = tomlkit.loads(f.read())

            node = data
            for key in spec["key_path"][:-1]:
                node = node[key]
            node[spec["key_path"][-1]] = verstr

            with open(file_path, "w") as f:
                if spec["format"] == "json":
                    json.dump(data, f, indent=4, sort_keys=True)
                else:
                    f.write(tomlkit.dumps(data))
        except IOError as e:
            VMN_LOGGER.error(
                f"Error writing {backend_name} ver file: {file_path}\n"
            )
            VMN_LOGGER.debug("Exception info: ", exc_info=True)

            raise IOError(e)
        except Exception as e:
            VMN_LOGGER.debug(e, exc_info=True)
            raise RuntimeError(e)

    def _write_version_to_generic_jinja(self, verstr, backend_conf):
        if self.dry_run:
            VMN_LOGGER.info(
                "Would have written to a version backend file:\n"
                f"backend: generic_jinja\n"
                f"version: {verstr}"
            )

            return

        # TODO:: The reason we need to set "version and base_version"
        # is because in this stage, we only have the "raw" current_version_info
        # "version and base_version" are added only in show. maybe think
        # about exporting to another function
        self.current_version_info["stamping"]["app"][
            "version"
        ] = VMNBackend.get_utemplate_formatted_version(
            verstr,
            self.template,
            self.hide_zero_hotfix,
        )

        self.current_version_info["stamping"]["app"][
            "base_version"
        ] = VMNBackend.get_base_vmn_version(
            verstr,
            self.hide_zero_hotfix,
        )

        for item in backend_conf:
            custom_path = None
            if "custom_keys_path" in item:
                custom_path = os.path.join(self.vmn_root_path, item["custom_keys_path"])

            tmplt_value = create_data_dict_for_jinja2(
                self.get_tag_name(
                    self.current_version_info["stamping"]["app"]["previous_version"]
                ),
                "HEAD",
                self.backend.repo_path,
                self.current_version_info,
                custom_path,
            )

            gen_jinja2_template_from_data(
                tmplt_value,
                os.path.join(self.vmn_root_path, item["input_file_path"]),
                os.path.join(self.vmn_root_path, item["output_file_path"]),
            )

    def _write_version_to_generic_selectors(self, verstr, backend_conf):
        for item in backend_conf:
            for selector in item["selectors_section"]:
                regex_selector = selector["regex_selector"]
                for k, v in SUPPORTED_REGEX_VARS.items():
                    regex_selector = regex_selector.replace(f"{{{{{k}}}}}", v)

                regex_sub = selector["regex_sub"]

                jinja_backend_conf = []
                temporary_jinja_template_paths = []
                for file_section in item["paths_section"]:
                    input_file_path = os.path.join(
                        self.vmn_root_path, file_section["input_file_path"]
                    )
                    with open(input_file_path, "r") as file:
                        content = file.read()

                        content = comment_out_jinja(content)

                    # Replace the matched version strings with regex_sub
                    content = re.sub(regex_selector, regex_sub, content)

                    raw_temporary_jinja_template_path = (
                        f'{file_section["input_file_path"]}.tmp.jinja2'
                    )
                    temporary_jinja_template_path = os.path.join(
                        self.vmn_root_path, raw_temporary_jinja_template_path
                    )

                    if self.dry_run:
                        VMN_LOGGER.info(
                            "Would have written to a version backend file:\n"
                            f"backend: generic_selectors\n"
                            f"version: {verstr}\n"
                            f"file: {temporary_jinja_template_path}\n"
                            f"with content:\n{content}"
                        )

                        continue

                    with open(temporary_jinja_template_path, "w") as file:
                        file.write(content)

                    temporary_jinja_template_paths.append(
                        (temporary_jinja_template_path, content)
                    )

                    d = {
                        "input_file_path": raw_temporary_jinja_template_path,
                        "output_file_path": raw_temporary_jinja_template_path,
                        "_output_file_path": file_section["output_file_path"],
                    }
                    if "custom_keys_path" in file_section:
                        d["custom_keys_path"] = file_section["custom_keys_path"]

                    jinja_backend_conf.append(d)

                self._write_version_to_generic_jinja(verstr, jinja_backend_conf)

                for jinja_backend_conf_item in jinja_backend_conf:
                    tmp_path = Path(self.vmn_root_path) / jinja_backend_conf_item["output_file_path"]
                    final_path = Path(self.vmn_root_path) / jinja_backend_conf_item["_output_file_path"]

                    final_path.parent.mkdir(parents=True, exist_ok=True)

                    shutil.copy2(tmp_path, final_path)

                for t, c in temporary_jinja_template_paths:
                    os.remove(t)
                    VMN_LOGGER.debug(f"Removed {t} with content:\n" f"{c}")

    def _write_version_to_vmn_version_file(self, verstr):
        file_path = self.version_file_path
        try:
            with open(file_path, "w") as fid:
                ver_dict = {"version_to_stamp_from": verstr}
                yaml.dump(ver_dict, fid)
        except IOError as e:
            VMN_LOGGER.error(f"Error writing ver file: {file_path}\n")
            VMN_LOGGER.debug("Exception info: ", exc_info=True)

            raise IOError(e)
        except Exception as e:
            VMN_LOGGER.debug(e, exc_info=True)
            raise RuntimeError(e)

    @staticmethod
    def parse_template(template: str) -> object:
        match = re.search(VMN_TEMPLATE_REGEX, template)
        if match is None:
            raise RuntimeError(f"Failed to parse template {template}")

        gdict = match.groupdict()

        return gdict

    def get_be_formatted_version(self, version):
        return VMNBackend.get_utemplate_formatted_version(
            version, self.template, self.hide_zero_hotfix
        )

    def create_config_files(self):
        # If there is no file - create it
        if not self.conf_file_exists:
            pathlib.Path(os.path.dirname(self.app_conf_path)).mkdir(
                parents=True, exist_ok=True
            )

            _key_to_attr = AppConf.conf_key_to_attr()
            conf_dict = {
                key: getattr(self, attr) for key, attr in _key_to_attr.items()
            }
            # Remove the internal "." entry from deps before writing
            conf_dict["deps"] = copy.deepcopy(self.configured_deps)
            conf_dict["deps"].pop(".", None)

            ver_conf_yml = {"conf": conf_dict}

            with open(self.app_conf_path, "w+") as f:
                msg = (
                    "# Autogenerated by vmn. You can edit this " "configuration file\n"
                )
                f.write(msg)
                yaml.dump(ver_conf_yml, f, sort_keys=True)

        if self.root_app_name is None:
            return

        if self.root_conf_file_exists:
            return

        pathlib.Path(os.path.dirname(self.app_conf_path)).mkdir(
            parents=True, exist_ok=True
        )

        ver_yml = {"conf": {"external_services": {}}}

        with open(self.root_app_conf_path, "w+") as f:
            f.write("# Autogenerated by vmn\n")
            yaml.dump(ver_yml, f, sort_keys=True)


