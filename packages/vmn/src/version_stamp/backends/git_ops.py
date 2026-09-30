#!/usr/bin/env python3
"""Git backend mixin: core operations (tag, push, pull, commit, clone)."""
import re
import time
from urllib.parse import quote as urlquote

import git

from version_stamp.core.constants import TAG_CHRONOLOGICAL_SPACING_SECONDS
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


def _strip_prefix(s, prefix):
    return s[len(prefix) :] if s.startswith(prefix) else s


def _push_error_mentions(exc, *markers):
    """Whether git's stderr (or a non-git error's message) names a marker.

    str() of a GitCommandError embeds the command line, so only its stderr
    is searched.
    """
    if isinstance(exc, git.exc.GitCommandError):
        text = str(exc.stderr or "")
    else:
        text = str(exc)
    return any(marker in text for marker in markers)


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
            self._be.git.execute(
                [
                    "git",
                    "update-ref",
                    f"refs/remotes/{self.selected_remote.name}/{remote_branch_name}",
                    "HEAD",
                ]
            )
        except Exception:
            VMN_LOGGER.debug(
                "Failed to update remote tracking ref after push",
                exc_info=True,
            )

    def _run_push(self, options, refspecs):
        self._be.git.execute(
            ["git", "push", "--porcelain", *options, self._get_push_target(), *refspecs]
        )

    def _push_with_ci_skip_fallback(self, refspecs, options=()):
        """Push refspecs with -o ci.skip, retrying without it if unsupported."""
        try:
            self._run_push([*options, "-o", "ci.skip"], refspecs)
        except Exception as exc:
            if not _push_error_mentions(exc, "push option", "ci.skip"):
                raise
            self._run_push(options, refspecs)

    def _push_atomically(self, refspecs):
        """Push all refspecs in one atomic push, non-atomic if unsupported."""
        try:
            self._push_with_ci_skip_fallback(refspecs, options=("--atomic",))
        except Exception as exc:
            if not _push_error_mentions(exc, "does not support --atomic"):
                raise
            self._push_with_ci_skip_fallback(refspecs)

    @measure_runtime_decorator
    def tag(self, tags, messages, ref="HEAD", push=False):
        if push and self.selected_remote is None:
            raise RuntimeError("Will not push tag without a configured remote")

        for tag, message in zip(tags, messages):
            # This is required in order to preserver chronological order when
            # listing tags since the taggerdate field is in seconds resolution
            time.sleep(TAG_CHRONOLOGICAL_SPACING_SECONDS)

            self._be.create_tag(tag, ref=ref, message=message)

            if not push:
                continue

            try:
                self._push_with_ci_skip_fallback([f"refs/tags/{tag}"])
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

        remote_branch_name = _strip_prefix(
            self.remote_active_branch, f"{self.selected_remote.name}/"
        )
        refspecs = [f"refs/heads/{self.active_branch}:{remote_branch_name}"]
        refspecs.extend(f"refs/tags/{tag}" for tag in tags)

        try:
            self._push_atomically(refspecs)
        except Exception:
            err_str = "Push has failed. Please verify that 'git push' works"
            VMN_LOGGER.error(err_str, exc_info=True)
            raise RuntimeError(err_str)

        if self._push_user and self._push_token:
            self._update_remote_tracking_ref(remote_branch_name)

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
            self._fetch("--tags", "--prune")
            return

        self.selected_remote.pull(ff_only=True)

    def _fetch(self, *args):
        """git fetch from the selected remote; a no-op without one."""
        if self.selected_remote is None:
            return
        self._be.git.execute(["git", "fetch", *args, self.selected_remote.name])

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
