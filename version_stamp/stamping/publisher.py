#!/usr/bin/env python3
"""VersionControlStamper — handles stamp, release, publish, changelog."""
import copy
import datetime
import glob
import os
import pathlib
import re
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from version_stamp.backends.base import VMNBackend
from version_stamp.core.constants import (
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    VMN_ROOT_TAG_REGEX,
    VMN_TAG_REGEX,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import branch_to_conf_prefix
from version_stamp.core.version_math import parse_conventional_commit_message
from version_stamp.stamping.base import IVersionsStamper


class VersionControlStamper(IVersionsStamper):
    @measure_runtime_decorator
    def __init__(self, arg_params):
        IVersionsStamper.__init__(self, arg_params)

    @measure_runtime_decorator
    def find_matching_version(self, verstr):
        """
        Try to find any version of the application matching the
        user's repositories local state
        :param verstr:
        :return:
        """

        if verstr is None:
            return None

        tag_formatted_app_name = VMNBackend.serialize_vmn_tag_name(
            self.name, verstr
        )
        base_verstr = VMNBackend.get_base_vmn_version(
            verstr, self.hide_zero_hotfix
        )
        release_tag_formatted_app_name = VMNBackend.serialize_vmn_tag_name(
            self.name, base_verstr
        )

        if (
            self.selected_tag != tag_formatted_app_name
            and self.selected_tag != tag_formatted_app_name.rstrip(".")
        ):
            # Get version info for tag
            tag_formatted_app_name, ver_infos = self.backend.get_tag_version_info(
                tag_formatted_app_name
            )
            if not ver_infos:
                VMN_LOGGER.error(
                    f"Failed to get version info for tag: {tag_formatted_app_name}"
                )
                return None

            self.enhance_ver_info(ver_infos)
        else:
            ver_infos = self.ver_infos_from_repo

        # TODO:: just a sanity? May be removed?
        if (
            tag_formatted_app_name not in ver_infos
            or ver_infos[tag_formatted_app_name] is None
        ):
            return None

        tmp = ver_infos[tag_formatted_app_name]["ver_info"]
        if release_tag_formatted_app_name in ver_infos:
            tmp = ver_infos[release_tag_formatted_app_name]["ver_info"]

        # Can happen if app's name is a prefix of another app
        if tmp["stamping"]["app"]["name"] != self.name:
            return None

        if tmp["stamping"]["app"]["release_mode"] == "init":
            return None

        found = True
        for k, v in tmp["stamping"]["app"]["changesets"].items():
            if k not in self.actual_deps_state:
                found = False
                break

            # when k is the "main repo" repo
            if self.repo_name == k:
                user_changeset = self.last_user_changeset

                if v["hash"] != user_changeset:
                    found = False
                    break
            elif v["hash"] != self.actual_deps_state[k]["hash"]:
                found = False
                break

        if found:
            return tmp

        return None

    @measure_runtime_decorator
    def release_app_version(self, tag_name, ver_info):
        if ver_info is None:
            VMN_LOGGER.error(
                f"Tag {tag_name} doesn't seem to exist. Wrong version specified?"
            )
            raise RuntimeError()

        if "whitelist_release_branches" in self.policies:
            policy_conf = self.policies["whitelist_release_branches"]
            tag_branch = self.backend.get_branch_from_changeset(
                self.backend.changeset(tag=tag_name)
            )

            if tag_branch not in policy_conf:
                err_msg = "Policy: whitelist_release_branches was violated. Refusing to release"
                VMN_LOGGER.error(err_msg)

                raise RuntimeError(err_msg)

        tmp = ver_info["stamping"]["app"]
        base_verstr = VMNBackend.get_base_vmn_version(
            tmp["_version"],
            hide_zero_hotfix=self.hide_zero_hotfix,
        )
        release_tag_name = VMNBackend.serialize_vmn_tag_name(
            self.name,
            base_verstr,
        )
        ver_info["vmn_info"] = self.current_version_info["vmn_info"]

        ver_info["stamping"]["app"]["_version"] = base_verstr
        ver_info["stamping"]["app"][
            "version"
        ] = VMNBackend.get_utemplate_formatted_version(
            base_verstr, self.template, self.hide_zero_hotfix
        )
        ver_info["stamping"]["app"]["prerelease"] = "release"
        ver_info["stamping"]["app"]["release_mode"] = "release"

        messages = [yaml.dump(ver_info, sort_keys=True)]

        self.backend.tag(
            [release_tag_name],
            messages,
            ref=self.backend.changeset(tag=tag_name),
            push=True,
        )

        return base_verstr

    @measure_runtime_decorator
    def add_metadata_to_version(self, tag_name, ver_info):
        props = VMNBackend.deserialize_tag_name(tag_name)
        res_ver = VMNBackend.serialize_vmn_version(
            props.verstr,
            buildmetadata=self.params["buildmetadata"],
            hide_zero_hotfix=self.hide_zero_hotfix,
        )

        buildmetadata_tag_name = VMNBackend.serialize_vmn_tag_name(
            self.name,
            res_ver,
        )

        ver_info["vmn_info"] = self.current_version_info["vmn_info"]
        ver_info["stamping"]["app"]["_version"] = res_ver
        ver_info["stamping"]["app"][
            "version"
        ] = VMNBackend.get_utemplate_formatted_version(
            res_ver, self.template, self.hide_zero_hotfix
        )
        ver_info["stamping"]["app"]["prerelease"] = "metadata"

        if self.params["version_metadata_url"] is not None:
            ver_info["stamping"]["app"]["version_metadata_url"] = self.params[
                "version_metadata_url"
            ]

        if self.params["version_metadata_path"] is not None:
            path = self.params["version_metadata_path"]

            with open(path) as f:
                ver_info["stamping"]["app"]["version_metadata"] = yaml.safe_load(f)

        (
            buildmetadata_tag_name,
            tag_ver_infos,
        ) = self.backend.get_tag_version_info(buildmetadata_tag_name)

        self.enhance_ver_info(tag_ver_infos)

        if buildmetadata_tag_name in tag_ver_infos:
            if tag_ver_infos[buildmetadata_tag_name]["ver_info"] != ver_info:
                VMN_LOGGER.error(
                    "Tried to add different metadata for the same version."
                )
                raise RuntimeError()

            return res_ver

        messages = [yaml.dump(ver_info, sort_keys=True)]

        self.backend.tag(
            [buildmetadata_tag_name],
            messages,
            ref=self.backend.changeset(tag=tag_name),
            push=True,
        )

        return res_ver

    @measure_runtime_decorator
    def stamp_app_version(self, from_verstr):
        props = VMNBackend.deserialize_vmn_version(from_verstr)
        initialprerelease = props.prerelease

        if initialprerelease == "release" and self.release_mode is None:
            VMN_LOGGER.error(
                "When not in release candidate mode, "
                "a release mode must be specified - use "
                "-r/--release-mode with one of major/minor/patch/hotfix"
            )
            raise RuntimeError()

        if initialprerelease != "release" and self.release_mode is None:
            base_version = VMNBackend.get_base_vmn_version(
                from_verstr,
                hide_zero_hotfix=self.hide_zero_hotfix,
            )
            release_tag_formatted_app_name = (
                VMNBackend.serialize_vmn_tag_name(self.name, base_version)
            )
            (
                release_tag_formatted_app_name,
                ver_infos,
            ) = self.backend.get_tag_version_info(release_tag_formatted_app_name)

            self.enhance_ver_info(ver_infos)

            if (
                release_tag_formatted_app_name in ver_infos
                and ver_infos[release_tag_formatted_app_name] is not None
            ):
                rel_verstr = ver_infos[release_tag_formatted_app_name]["ver_info"][
                    "stamping"
                ]["app"]["_version"]
                VMN_LOGGER.error(
                    f"The version {rel_verstr} was already released. "
                    "Will refuse to stamp prerelease version"
                )
                raise RuntimeError()

        current_version, prerelease_count = self.gen_advanced_version(from_verstr)

        info = {}
        if self.extra_info:
            info["env"] = dict(os.environ)

        release_mode = self.release_mode
        cur_props = VMNBackend.deserialize_vmn_version(current_version)

        if cur_props.prerelease != "release":
            release_mode = "prerelease"

        if "whitelist_release_branches" in self.policies:
            policy_conf = self.policies["whitelist_release_branches"]
            if (
                release_mode != "prerelease"
                and self.backend.active_branch not in policy_conf
            ):
                err_msg = (
                    "Policy: whitelist_release_branches was violated. Refusing to stamp"
                )
                VMN_LOGGER.error(err_msg)

                raise RuntimeError(err_msg)

        self.update_stamping_info(
            info,
            from_verstr,
            current_version,
            release_mode,
            prerelease_count,
        )

        return current_version

    @measure_runtime_decorator
    def update_stamping_info(
        self,
        info,
        initial_version,
        current_version,
        release_mode,
        prerelease_count,
    ):
        props = VMNBackend.deserialize_vmn_version(current_version)

        self.current_version_info["stamping"]["app"]["_version"] = current_version
        self.current_version_info["stamping"]["app"]["prerelease"] = props.prerelease

        self.current_version_info["stamping"]["app"][
            "previous_version"
        ] = initial_version
        self.current_version_info["stamping"]["app"]["release_mode"] = release_mode
        self.current_version_info["stamping"]["app"]["info"] = copy.deepcopy(info)
        self.current_version_info["stamping"]["app"][
            "stamped_on_branch"
        ] = self.backend.active_branch
        self.current_version_info["stamping"]["app"][
            "stamped_on_remote_branch"
        ] = self.backend.remote_active_branch
        self.current_version_info["stamping"]["app"][
            "prerelease_count"
        ] = copy.deepcopy(prerelease_count)

    @measure_runtime_decorator
    def stamp_root_app_version(self, override_version=None):
        if self.root_app_name is None:
            return None

        tag_name, ver_infos = self.get_first_reachable_version_info(
            self.root_app_name,
            root_context=True,
            type=RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
        )

        self.enhance_ver_info(ver_infos)

        if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
            VMN_LOGGER.error(
                f"Version information for {self.root_app_name} was not found"
            )
            raise RuntimeError()

        # TODO: think about this case
        if "version" not in ver_infos[tag_name]["ver_info"]["stamping"]["root_app"]:
            VMN_LOGGER.error(
                f"Root app name is {self.root_app_name} and app name is {self.name}. "
                f"However no version information for root was found"
            )
            raise RuntimeError()

        old_version = int(
            ver_infos[tag_name]["ver_info"]["stamping"]["root_app"]["version"]
        )
        if override_version is None:
            override_version = old_version

        root_version = int(override_version) + 1

        root_app = ver_infos[tag_name]["ver_info"]["stamping"]["root_app"]
        services = copy.deepcopy(root_app["services"])

        services[self.name] = self.current_version_info["stamping"]["app"]["_version"]

        self.current_version_info["stamping"]["root_app"].update(
            {
                "version": root_version,
                "services": services,
            }
        )

        return "{0}".format(root_version)

    def get_files_to_add_to_index(self, paths):
        changed = [
            os.path.join(self.vmn_root_path, item.a_path.replace("/", os.sep))
            for item in self.backend._be.index.diff(None)
        ]
        untracked = [
            os.path.join(self.vmn_root_path, item.replace("/", os.sep))
            for item in self.backend._be.untracked_files
        ]

        version_files = []
        for path in paths:
            if path in changed or path in untracked:
                version_files.append(path)

        return version_files

    @measure_runtime_decorator
    def publish_stamp(self, app_version, root_app_version):
        app_msg = {
            "vmn_info": self.current_version_info["vmn_info"],
            "stamping": {"app": self.current_version_info["stamping"]["app"]},
        }

        if not self.should_publish:
            return 0

        self.write_version_to_file(version_number=app_version)

        version_files_to_add = self.get_files_to_add_to_index(self.version_files)

        for backend in self.version_backends:
            try:
                backend_conf = self.version_backends[backend]
                if backend in self._STRUCTURED_BACKEND_SPEC:
                    self._add_files_simple_backend(version_files_to_add, backend_conf)
                else:
                    handler = getattr(self, f"_add_files_{backend}")
                    handler(version_files_to_add, backend_conf)
            except AttributeError:
                VMN_LOGGER.warning(f"Unsupported version backend {backend}")
                continue

        if self.create_verinfo_files:
            self.create_verinfo_file(app_msg, version_files_to_add, app_version)

        if self.root_app_name is not None:
            root_app_msg = {
                "stamping": {
                    "root_app": self.current_version_info["stamping"]["root_app"]
                },
                "vmn_info": self.current_version_info["vmn_info"],
            }

            tmp = self.get_files_to_add_to_index([self.root_app_conf_path])
            if tmp:
                version_files_to_add.extend(tmp)

            if self.create_verinfo_files:
                self.create_verinfo_root_file(
                    root_app_msg, root_app_version, version_files_to_add
                )

        self._generate_changelog(app_version, version_files_to_add)

        commit_msg = None
        if self.current_version_info["stamping"]["app"]["release_mode"] == "init":
            commit_msg = f"{self.name}: Stamped initial version {app_version}\n\n"
        else:
            extra_commit_message = self.params["extra_commit_message"]
            commit_msg = (
                f"{self.name}: Stamped version {app_version}\n{extra_commit_message}\n"
            )

        self.current_version_info["stamping"]["msg"] = commit_msg

        prev_changeset = self.backend.changeset()

        try:
            self.publish_commit(version_files_to_add)
        except Exception:
            VMN_LOGGER.debug("Logged Exception message: ", exc_info=True)
            VMN_LOGGER.info("Reverting vmn changes... ")
            if self.dry_run:
                VMN_LOGGER.info("Would have tried to revert a vmn commit")
            else:
                self.backend.revert_vmn_commit(prev_changeset, self.version_files)

            # TODO:: turn to error codes (enums). This one means - exit without retries
            return 3

        tag = f'{self.name.replace("/", "-")}_{app_version}'
        match = re.search(VMN_TAG_REGEX, tag)
        if match is None:
            VMN_LOGGER.error(
                f"Tag {tag} doesn't comply to vmn version format"
                f"Reverting vmn changes ..."
            )
            if self.dry_run:
                VMN_LOGGER.info("Would have reverted vmn commit.")
            else:
                self.backend.revert_vmn_commit(prev_changeset, self.version_files)

            return 3

        tags = [tag]
        msgs = [app_msg]

        if self.root_app_name is not None:
            msgs.append(root_app_msg)
            tag = f"{self.root_app_name}_{root_app_version}"
            match = re.search(VMN_ROOT_TAG_REGEX, tag)
            if match is None:
                VMN_LOGGER.error(
                    f"Tag {tag} doesn't comply to vmn version format"
                    f"Reverting vmn changes ..."
                )
                if self.dry_run:
                    VMN_LOGGER.info("Would have reverted vmn commit.")
                else:
                    self.backend.revert_vmn_commit(prev_changeset, self.version_files)

                return 3

            tags.append(tag)

        all_tags = []
        all_tags.extend(tags)

        try:
            for t, m in zip(tags, msgs):
                if self.dry_run:
                    VMN_LOGGER.info(
                        "Would have created tag:\n"
                        f"{t}\n"
                        f"Tag content:\n{yaml.dump(m, sort_keys=True)}"
                    )
                else:
                    self.backend.tag([t], [yaml.dump(m, sort_keys=True)])
        except Exception:
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            VMN_LOGGER.info(f"Reverting vmn changes for tags: {tags} ... ")
            if self.dry_run:
                VMN_LOGGER.info(
                    f"Would have reverted vmn commit and delete tags:\n{all_tags}"
                )
            else:
                self.backend.revert_vmn_commit(
                    prev_changeset, self.version_files, all_tags
                )

            return 1

        try:
            if self.dry_run:
                VMN_LOGGER.info(
                    "Would have pushed with tags.\n" f"tags: {all_tags} "
                )
            else:
                self.backend.push(all_tags)

                count = 0
                res = self.backend.check_for_outgoing_changes()
                while count < 5 and res:
                    count += 1
                    VMN_LOGGER.error(
                        f"BUG: Somehow we have outgoing changes right "
                        f"after publishing:\n{res}"
                    )
                    time.sleep(60)
                    res = self.backend.check_for_outgoing_changes()

                if count == 5 and res:
                    raise RuntimeError(
                        f"BUG: Somehow we have outgoing changes right "
                        f"after publishing:\n{res}"
                    )
        except Exception:
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            VMN_LOGGER.info(f"Reverting vmn changes for tags: {tags} ...")
            if self.dry_run:
                VMN_LOGGER.info(
                    f"Would have reverted vmn commit and delete tags:\n{all_tags}"
                )
            else:
                self.backend.revert_vmn_commit(
                    prev_changeset, self.version_files, all_tags
                )

            return 2

        # Best-effort GitHub Release creation after successful push
        self._create_github_release(tags[0], app_version)

        return 0

    def _generate_changelog(self, app_version, version_files_to_add):
        """Generate a changelog entry from conventional commits and prepend to CHANGELOG.md."""
        if not self.changelog:
            return

        if self.selected_tag is None:
            VMN_LOGGER.debug(
                "No previous version tag found, skipping changelog generation"
            )
            return

        changelog_path_rel = self.changelog.get("path", "CHANGELOG.md")
        changelog_path = os.path.join(self.vmn_root_path, changelog_path_rel)

        # Collect commits grouped by type
        type_labels = {
            "feat": "Features",
            "fix": "Bug Fixes",
            "perf": "Performance Improvements",
            "refactor": "Refactoring",
            "docs": "Documentation",
            "style": "Style",
            "test": "Tests",
            "build": "Build",
            "ci": "CI",
            "chore": "Chores",
            "revert": "Reverts",
        }

        breaking_changes = []
        grouped_commits = {}

        try:
            for msg, short_hash in self.backend.get_commits_info_iter(
                self.selected_tag
            ):
                try:
                    res = parse_conventional_commit_message(msg)
                except ValueError:
                    continue

                description = res["description"].strip()
                scope = res.get("scope")
                is_breaking = res.get("bc") == "!"

                # Check footer for BREAKING CHANGE
                footer = res.get("footer") or ""
                if "BREAKING CHANGE" in footer or "BREAKING-CHANGE" in footer:
                    is_breaking = True

                prefix = f"**{scope}:** " if scope else ""
                entry = f"- {prefix}{description} ({short_hash})"

                if is_breaking:
                    breaking_changes.append(entry)
                else:
                    commit_type = res["type"].strip()
                    label = type_labels.get(commit_type, "Other Changes")
                    grouped_commits.setdefault(label, []).append(entry)
        except Exception:
            VMN_LOGGER.debug(
                "Failed to iterate commits for changelog", exc_info=True
            )
            return

        if not grouped_commits and not breaking_changes:
            VMN_LOGGER.debug(
                "No conventional commits found, skipping changelog generation"
            )
            return

        # Build the changelog entry
        today = datetime.date.today().isoformat()
        lines = [f"## [{app_version}] - {today}", ""]

        # Section ordering: Breaking Changes first, then Features, Bug Fixes, rest
        section_order = ["Breaking Changes", "Features", "Bug Fixes"]

        if breaking_changes:
            lines.append("### Breaking Changes")
            lines.extend(breaking_changes)
            lines.append("")

        for section in section_order:
            if section == "Breaking Changes":
                continue
            if section in grouped_commits:
                lines.append(f"### {section}")
                lines.extend(grouped_commits.pop(section))
                lines.append("")

        for section in sorted(grouped_commits.keys()):
            lines.append(f"### {section}")
            lines.extend(grouped_commits[section])
            lines.append("")

        new_entry = "\n".join(lines)

        if self.dry_run:
            VMN_LOGGER.info(
                f"Would have written changelog entry to {changelog_path}:\n{new_entry}"
            )
            return

        # Read existing content or start fresh
        existing_content = ""
        if os.path.exists(changelog_path):
            try:
                with open(changelog_path, "r") as f:
                    existing_content = f.read()
            except Exception:
                VMN_LOGGER.debug(
                    "Failed to read existing changelog", exc_info=True
                )

        if existing_content:
            # Insert after the first header line if present, otherwise prepend
            header_match = re.match(r"^(# .+\n(?:\n)?)", existing_content)
            if header_match:
                header = header_match.group(1)
                rest = existing_content[len(header):]
                updated = header + "\n" + new_entry + "\n" + rest
            else:
                updated = new_entry + "\n\n" + existing_content
        else:
            updated = "# Changelog\n\n" + new_entry + "\n"

        try:
            with open(changelog_path, "w") as f:
                f.write(updated)
            version_files_to_add.append(changelog_path)
            VMN_LOGGER.info(
                f"Generated changelog entry for version {app_version}"
            )
        except Exception:
            VMN_LOGGER.debug(
                "Failed to write changelog file", exc_info=True
            )

    def _create_github_release(self, tag, app_version):
        """Create a GitHub Release via gh CLI. Best-effort -- failures log warnings."""
        try:
            if not self.github_release:
                return

            if self.dry_run:
                VMN_LOGGER.info(
                    f"Would have created GitHub Release for tag {tag}"
                )
                return

            if not shutil.which("gh"):
                VMN_LOGGER.warning(
                    "gh CLI not found. Skipping GitHub Release creation."
                )
                return

            if not os.environ.get("GITHUB_TOKEN") and not os.environ.get("GH_TOKEN"):
                VMN_LOGGER.warning(
                    "Neither GITHUB_TOKEN nor GH_TOKEN is set. "
                    "Skipping GitHub Release creation."
                )
                return

            body = self._build_release_body(app_version)

            cmd = [
                "gh", "release", "create", tag,
                "--title", f"v{app_version}",
                "--notes", body,
            ]

            if self.github_release.get("draft", False):
                cmd.append("--draft")

            if self.prerelease:
                cmd.append("--prerelease")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.vmn_root_path,
            )

            if result.returncode != 0:
                VMN_LOGGER.warning(
                    f"Failed to create GitHub Release: {result.stderr.strip()}"
                )
            else:
                VMN_LOGGER.info(
                    f"Created GitHub Release for {tag}"
                )
        except Exception:
            VMN_LOGGER.warning(
                "GitHub Release creation failed (best-effort).",
                exc_info=True,
            )

    def _build_release_body(self, app_version):
        """Build release notes body for a GitHub Release."""
        # Try to extract the relevant section from CHANGELOG.md
        changelog_path = os.path.join(self.vmn_root_path, "CHANGELOG.md")
        if os.path.isfile(changelog_path):
            try:
                with open(changelog_path, "r") as f:
                    content = f.read()

                # Look for a section header like ## [1.2.3] or ## [v1.2.3]
                section_pattern = (
                    rf"## \[v?{re.escape(app_version)}\][^\n]*\n"
                )
                match = re.search(section_pattern, content)
                if match:
                    start = match.end()
                    # Find the next ## heading or end of file
                    next_section = re.search(r"\n## \[", content[start:])
                    end = start + next_section.start() if next_section else len(content)
                    section_body = content[start:end].strip()
                    if section_body:
                        return section_body
            except Exception:
                VMN_LOGGER.debug(
                    "Could not read CHANGELOG.md for release notes.",
                    exc_info=True,
                )

        # Fall back to listing commits since the previous tag
        try:
            prev_tag = self.selected_tag
            if prev_tag:
                lines = []
                for msg in self.backend.get_commits_range_iter(prev_tag):
                    first_line = msg.split("\n", 1)[0]
                    lines.append(f"- {first_line}")
                if lines:
                    return "\n".join(lines)
        except Exception:
            VMN_LOGGER.debug(
                "Could not generate commit list for release notes.",
                exc_info=True,
            )

        return f"Release {app_version}"

    def _add_files_generic_selectors(self, version_files_to_add, backend_conf):
        for item in backend_conf:
            for d in item["paths_section"]:
                for _, v in d.items():
                    file_path = os.path.join(self.vmn_root_path, v)
                    version_files_to_add.append(file_path)

    def _add_files_generic_jinja(self, version_files_to_add, backend_conf):
        for item in backend_conf:
            for _, v in item.items():
                file_path = os.path.join(self.vmn_root_path, v)
                version_files_to_add.append(file_path)

    def _add_files_simple_backend(self, version_files_to_add, backend_conf):
        file_path = os.path.join(self.vmn_root_path, backend_conf["path"])
        version_files_to_add.append(file_path)

    @measure_runtime_decorator
    def publish_commit(self, version_files_to_add):
        cur_branch = self.backend.active_branch
        path = os.path.join(
            self.app_dir_path,
            "*_conf.yml",
        )
        list_of_files = glob.glob(path)

        # Detect legacy branch configs in subdirectories (created before branch
        # name sanitization replaced "/" with "-" in conf filenames).
        try:
            for entry in os.scandir(self.app_dir_path):
                if entry.is_dir():
                    for fname in os.listdir(entry.path):
                        if fname.endswith("_conf.yml") or fname == "conf.yml":
                            legacy = os.path.join(entry.path, fname)
                            VMN_LOGGER.warning(
                                f"Found legacy branch config in subdirectory: {legacy}. "
                                f"Branch configs should be flat files like "
                                f"'<branch>_conf.yml'."
                            )
        except OSError:
            pass

        branch_conf_path = os.path.join(
            self.app_dir_path, f"{branch_to_conf_prefix(cur_branch)}_conf.yml"
        )

        if self.dry_run:
            if list_of_files:
                VMN_LOGGER.info(
                    "Would have removed config files:\n"
                    f"{set(list_of_files) - {branch_conf_path} }"
                )

            VMN_LOGGER.info(
                "Would have created commit with message:\n"
                f'{self.current_version_info["stamping"]["msg"]}'
            )
        else:
            for f in set(list_of_files) - {branch_conf_path}:
                try:
                    self.backend._be.index.remove([f], working_tree=True)
                except Exception:
                    pass

                try:
                    f_to_rem = pathlib.Path(f)
                    f_to_rem.unlink()
                except Exception:
                    pass

            self.backend.commit(
                message=self.current_version_info["stamping"]["msg"],
                user="vmn",
                include=version_files_to_add,
            )

    def _write_verinfo_file(self, msg, version_id, dir_path, label, version_files_to_add):
        if self.dry_run:
            VMN_LOGGER.info(
                f"Would have written to {label} verinfo file:\n"
                f"path: {dir_path} version: {version_id}\n"
                f"message: {msg}"
            )
        else:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            path = os.path.join(dir_path, f"{version_id}.yml")
            with open(path, "w") as f:
                f.write(yaml.dump(msg, sort_keys=True))
            version_files_to_add.append(path)

    @measure_runtime_decorator
    def create_verinfo_root_file(
        self, root_app_msg, root_app_version, version_files_to_add
    ):
        dir_path = os.path.join(self.root_app_dir_path, "root_verinfo")
        self._write_verinfo_file(root_app_msg, root_app_version, dir_path, "root", version_files_to_add)

    @measure_runtime_decorator
    def create_verinfo_file(self, app_msg, version_files_to_add, verstr):
        dir_path = os.path.join(self.app_dir_path, "verinfo")
        self._write_verinfo_file(app_msg, verstr, dir_path, "app", version_files_to_add)

    @measure_runtime_decorator
    def retrieve_remote_changes(self):
        self.backend.pull()


