#!/usr/bin/env python3
"""Git backend mixin: changeset, deps, revert, commit history."""
import configparser
import os
import re

import git

from version_stamp.backends.iterators import CommitInfoIterator, CommitMessageIterator
from version_stamp.core.constants import INIT_COMMIT_MESSAGE, VMN_USER_NAME
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class GitHistoryMixin:
    """Methods for changeset, deps, revert, log inspection. Mixed into GitBackend."""

    @measure_runtime_decorator
    def add_git_user_cfg_if_missing(self):
        try:
            self._be.config_reader().get_value("user", "name")
            self._be.config_reader().get_value("user", "email")
        except (configparser.NoSectionError, configparser.NoOptionError):
            self._be.git.set_persistent_git_options(
                c=[f'user.name="{VMN_USER_NAME}"', f'user.email="{VMN_USER_NAME}"']
            )

    @measure_runtime_decorator
    def get_actual_deps_state(self, vmn_root_path, paths):
        actual_deps_state = {}
        for path in paths:
            full_path = os.path.join(vmn_root_path, path)
            details = self.__class__.get_repo_details(full_path)
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
    def get_commit_object_from_commit_hex(self, hex):
        return self._be.commit(hex)

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

    def parse_git_log_to_commit_for_specific_file(self, from_commit, to_commit, filenames):
        try:
            if not filenames:
                return {}, []

            log_format = "--format=%H %s"
            git_log_command = [
                "log",
                "--ancestry-path",
                log_format,
                f"{from_commit}..{to_commit}",
                "--",
            ] + filenames

            logs = self._be.git.execute(["git"] + git_log_command)

            log_entries = logs.splitlines()
            result = set()
            result_list = []

            for entry in log_entries:
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

    def _iter_commits_in_range(self, tag_name, to_hex="HEAD"):
        """Return a raw GitPython commit iterator for the range tag..to_hex."""
        from_hex = self._be.tags[tag_name].commit

        shallow = os.path.exists(os.path.join(self._be.common_dir, "shallow"))
        if shallow:
            self._be.git.execute(["git", "fetch", "--unshallow"])

        return self._be.iter_commits(f"{from_hex}..{to_hex}")

    def get_commits_range_iter(self, tag_name, to_hex="HEAD"):
        return CommitMessageIterator(self._iter_commits_in_range(tag_name, to_hex))

    def get_commits_info_iter(self, tag_name, to_hex="HEAD"):
        """Like get_commits_range_iter but yields (message, short_hash) tuples."""
        return CommitInfoIterator(self._iter_commits_in_range(tag_name, to_hex))
