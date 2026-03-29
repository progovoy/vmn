#!/usr/bin/env python3
"""Git backend mixin: core operations (tag, push, pull, commit, clone)."""
import logging
import time

import git

from version_stamp.core.constants import TAG_CHRONOLOGICAL_SPACING_SECONDS
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class GitOpsMixin:
    """Methods for basic git operations. Mixed into GitBackend."""

    def _push_with_ci_skip_fallback(self, refspec):
        """Push a refspec, trying with -o ci.skip first, falling back to without."""
        try:
            self._be.git.execute(
                [
                    "git",
                    "push",
                    "--porcelain",
                    "-o",
                    "ci.skip",
                    self.selected_remote.name,
                    refspec,
                ]
            )
        except Exception:
            self._be.git.execute(
                [
                    "git",
                    "push",
                    "--porcelain",
                    self.selected_remote.name,
                    refspec,
                ]
            )

    @measure_runtime_decorator
    def tag(self, tags, messages, ref="HEAD", push=False):
        if push and self.remote_active_branch is None:
            raise RuntimeError("Will not push remote branch does not exist")

        for tag, message in zip(tags, messages):
            # This is required in order to preserver chronological order when
            # listing tags since the taggerdate field is in seconds resolution
            time.sleep(TAG_CHRONOLOGICAL_SPACING_SECONDS)

            self._be.create_tag(tag, ref=ref, message=message)

            if not push:
                continue

            try:
                self._push_with_ci_skip_fallback(f"refs/tags/{tag}")
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
    def push(self, tags=()):
        if self.detached_head:
            raise RuntimeError("Will not push from detached head")

        if self.remote_active_branch is None:
            raise RuntimeError("Will not push remote branch does not exist")

        remote_branch_name_no_remote_name = "".join(
            self.remote_active_branch.split(f"{self.selected_remote.name}/")
        )

        try:
            self._push_with_ci_skip_fallback(
                f"refs/heads/{self.active_branch}:{remote_branch_name_no_remote_name}"
            )
        except Exception:
            err_str = "Push has failed. Please verify that 'git push' works"
            VMN_LOGGER.error(err_str, exc_info=True)
            raise RuntimeError(err_str)

        for tag in tags:
            self._push_with_ci_skip_fallback(f"refs/tags/{tag}")

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
    def is_path_tracked(self, path):
        try:
            self._be.git.execute(["git", "ls-files", "--error-unmatch", path])
            return True
        except Exception:
            VMN_LOGGER.debug(f"Logged exception for path {path}: ", exc_info=True)
            return False

    @staticmethod
    def clone(path, remote):
        git.Repo.clone_from(f"{remote}", f"{path}")
