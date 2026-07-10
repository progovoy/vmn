#!/usr/bin/env python3
"""Git backend mixin: core operations (tag, push, pull, commit, clone)."""
import time
import re
from urllib.parse import quote as urlquote

import git

from version_stamp.core.constants import TAG_CHRONOLOGICAL_SPACING_SECONDS
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class GitOpsMixin:
    """Methods for basic git operations. Mixed into GitBackend."""

    _push_user = None
    _push_token = None

    def set_push_credentials(self, user, token):
        """Set alternative credentials for push operations."""
        self._push_user = user
        self._push_token = token

    def _get_push_target(self):
        """Return the push target (remote name or authenticated URL)."""
        if self._push_user and self._push_token:
            remote_url = tuple(self.selected_remote.urls)[0]
            authenticated_url = self._inject_credentials_into_url(remote_url)
            if authenticated_url:
                return authenticated_url
        return self.selected_remote.name

    def _inject_credentials_into_url(self, url):
        """Rewrite a GitHub remote URL to use HTTPS with embedded credentials.

        Supports:
          - https://github.com/owner/repo.git
          - git@github.com:owner/repo.git
          - ssh://git@github.com/owner/repo.git
        """
        user = urlquote(self._push_user, safe="")
        token = urlquote(self._push_token, safe="")

        # HTTPS URL
        match = re.match(r"https?://([^/]+)/(.*)", url)
        if match:
            host = match.group(1)
            # Strip any existing credentials from host
            if "@" in host:
                host = host.split("@", 1)[1]
            return f"https://{user}:{token}@{host}/{match.group(2)}"

        # SSH shorthand: git@github.com:owner/repo.git
        match = re.match(r"git@([^:]+):(.*)", url)
        if match:
            host = match.group(1)
            return f"https://{user}:{token}@{host}/{match.group(2)}"

        # SSH URL: ssh://git@github.com/owner/repo.git
        match = re.match(r"ssh://[^@]+@([^/]+)/(.*)", url)
        if match:
            host = match.group(1)
            return f"https://{user}:{token}@{host}/{match.group(2)}"

        VMN_LOGGER.warning(
            f"Could not inject credentials into remote URL: {url}. "
            "Falling back to default remote."
        )
        return None

    def _update_remote_tracking_ref(self, remote_branch_name):
        """Update the remote tracking ref after pushing via explicit URL.

        When pushing to a URL instead of a named remote, git does not update
        the remote tracking refs (e.g. origin/main). This causes
        check_for_outgoing_changes to falsely report outgoing commits.
        """
        try:
            self._be.git.execute([
                "git", "update-ref",
                f"refs/remotes/{self.remote_active_branch}",
                "HEAD",
            ])
        except Exception:
            VMN_LOGGER.debug(
                "Failed to update remote tracking ref after push",
                exc_info=True,
            )

    def _push_with_ci_skip_fallback(self, refspec):
        """Push a refspec, trying with -o ci.skip first, falling back to without."""
        push_target = self._get_push_target()
        try:
            self._be.git.execute(
                [
                    "git",
                    "push",
                    "--porcelain",
                    "-o",
                    "ci.skip",
                    push_target,
                    refspec,
                ]
            )
        except Exception:
            self._be.git.execute(
                [
                    "git",
                    "push",
                    "--porcelain",
                    push_target,
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
        if self.selected_remote is None:
            raise RuntimeError(
                "No git remote is configured; cannot push. "
                "Add one with 'git remote add origin <url>'."
            )

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

        if self._push_user and self._push_token:
            self._update_remote_tracking_ref(remote_branch_name_no_remote_name)

        for tag in tags:
            self._push_with_ci_skip_fallback(f"refs/tags/{tag}")

    @measure_runtime_decorator
    def pull(self):
        if self.selected_remote is None:
            VMN_LOGGER.info(
                f"{self.repo_path}: no git remote configured – skipping pull"
            )
            return

        if self.detached_head:
            VMN_LOGGER.info(
                f"{self.repo_path}: in detached HEAD – fetching instead of pulling"
            )
            self._be.git.execute(["git", "fetch", self.selected_remote.name, "--tags", "--prune"])
            return

        self.selected_remote.pull(ff_only=True)

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
