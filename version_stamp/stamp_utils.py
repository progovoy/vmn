#!/usr/bin/env python3
import sys
import os
import git
import logging
from pathlib import Path
import re
import time

import yaml

import configparser

INIT_COMMIT_MESSAGE = "Initialized vmn tracking"

VMN_VERSION_FORMAT = "{major}.{minor}.{patch}[.{hotfix}][-{prerelease}]"
VMN_DEFAULT_TEMPLATE = (
    "[{major}][.{minor}][.{patch}][.{hotfix}]"
    "[-{prerelease}][+{buildmetadata}][-{releasenotes}]"
)

SEMVER_REGEX = (
    "^(?P<major>0|[1-9]\d*)\."
    "(?P<minor>0|[1-9]\d*)\."
    "(?P<patch>0|[1-9]\d*)"
    "(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    "(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
# Regex for matching versions stamped by vmn
VMN_REGEX = (
    "^(?P<major>0|[1-9]\d*)\."
    "(?P<minor>0|[1-9]\d*)\."
    "(?P<patch>0|[1-9]\d*)"
    "(?:\.(?P<hotfix>0|[1-9]\d*))?"
    "(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    "(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    "(?:-(?P<releasenotes>(?:rn\.[1-9]\d*))+)?$"
)
# TODO: create an abstraction layer on top of tag names versus the actual Semver versions
VMN_TAG_REGEX = (
    "^(?P<app_name>[^\/]+)_(?P<major>0|[1-9]\d*)\."
    "(?P<minor>0|[1-9]\d*)\."
    "(?P<patch>0|[1-9]\d*)"
    "(?:\.(?P<hotfix>0|[1-9]\d*))?"
    "(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    "(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?"
    "(?:-(?P<releasenotes>(?:rn\.[1-9]\d*))+)?$"
)

VMN_ROOT_TAG_REGEX = "(?P<app_name>[^\/]+)_(?P<version>0|[1-9]\d*)$"

VMN_TEMPLATE_REGEX = (
    "^(?:\[(?P<major_template>[^\{\}]*\{major\}[^\{\}]*)\])?"
    "(?:\[(?P<minor_template>[^\{\}]*\{minor\}[^\{\}]*)\])?"
    "(?:\[(?P<patch_template>[^\{\}]*\{patch\}[^\{\}]*)\])?"
    "(?:\[(?P<hotfix_template>[^\{\}]*\{hotfix\}[^\{\}]*)\])?"
    "(?:\[(?P<prerelease_template>[^\{\}]*\{prerelease\}[^\{\}]*)\])?"
    "(?:\[(?P<buildmetadata_template>[^\{\}]*\{buildmetadata\}[^\{\}]*)\])?"
    "(?:\[(?P<releasenotes_template>[^\{\}]*\{releasenotes\}[^\{\}]*)\])?$"
)

VMN_USER_NAME = "vmn"
LOGGER = None


def init_stamp_logger(debug=False):
    global LOGGER

    LOGGER = logging.getLogger(VMN_USER_NAME)
    for handler in LOGGER.handlers:
        LOGGER.removeHandler(handler)

    if debug:
        LOGGER.setLevel(logging.DEBUG)
    else:
        LOGGER.setLevel(logging.INFO)
    format = "[%(levelname)s] %(message)s"

    formatter = logging.Formatter(format, "%Y-%m-%d %H:%M:%S")

    cons_handler = logging.StreamHandler(sys.stdout)
    cons_handler.setFormatter(formatter)
    LOGGER.addHandler(cons_handler)

    return LOGGER


class VersionControlBackend(object):
    def __init__(self, type):
        self._type = type

    def __del__(self):
        pass

    def type(self):
        return self._type

    @staticmethod
    def get_tag_formatted_app_name(
        app_name, version=None, prerelease=None, prerelease_count=None
    ):
        app_name = app_name.replace("/", "-")

        if version is None:
            return f"{app_name}"
        else:
            verstr = f"{app_name}_{version}"
            if prerelease is not None and prerelease != "release":
                verstr = f"{verstr}-{prerelease}{prerelease_count[prerelease]}"

            return verstr

    @staticmethod
    def get_tag_properties(vmn_tag):
        ret = {
            "app_name": None,
            "type": "version",
            "version": None,
            "root_version": None,
            "hotfix": None,
            "prerelease": None,
            "buildmetadata": None,
            "releasenotes": None,
        }

        match = re.search(VMN_ROOT_TAG_REGEX, vmn_tag)
        if match is not None:
            gdict = match.groupdict()
            if gdict["version"] is not None:
                int(gdict["version"])
                ret["root_version"] = gdict["version"]
                ret["type"] = "root"

            return ret

        match = re.search(VMN_TAG_REGEX, vmn_tag)
        if match is None:
            raise RuntimeError(f"Tag {vmn_tag} doesn't comply to vmn version format")

        gdict = match.groupdict()
        ret["app_name"] = gdict["app_name"].replace("-", "/")
        ret["version"] = f'{gdict["major"]}.{gdict["minor"]}.{gdict["patch"]}'
        ret["hotfix"] = "0"

        if gdict["hotfix"] is not None:
            ret["hotfix"] = gdict["hotfix"]

        if gdict["prerelease"] is not None:
            ret["prerelease"] = gdict["prerelease"]
            ret["type"] = "prerelease"

        if gdict["buildmetadata"] is not None:
            ret["buildmetadata"] = gdict["buildmetadata"]
            ret["type"] = "buildmetadata"

        if gdict["releasenotes"] is not None:
            ret["releasenotes"] = gdict["releasenotes"]
            ret["type"] = "releasenotes"

        return ret

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
            "releasenotes",
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


class GitBackend(VersionControlBackend):
    def __init__(self, repo_path, revert=False, pull=False):
        VersionControlBackend.__init__(self, "git")

        self._be = git.Repo(repo_path, search_parent_directories=True)
        self._origin = self._be.remote(name="origin")

        if revert:
            self._be.head.reset(working_tree=True)
        if pull:
            self.pull()

        self._be.git.fetch("--tags")

    def __del__(self):
        self._be.close()

    def is_path_tracked(self, path):
        try:
            self._be.git.execute(["git", "ls-files", "--error-unmatch", path])
            return True
        except:
            return False

    def tag(self, tags, messages, ref="HEAD"):
        for tag, message in zip(tags, messages):
            # This is required in order to preserver chronological order when
            # listing tags since the taggerdate field is in seconds resolution
            time.sleep(1.1)
            self._be.create_tag(
                tag,
                ref=ref,
                message=message,
            )

    def push(self, tags=()):
        try:
            ret = self._origin.push(
                f"refs/heads/{self.get_active_branch()}", o="ci.skip"
            )
        except Exception:
            ret = self._origin.push(f"refs/heads/{self.get_active_branch()}")

        if ret[0].old_commit is None:
            if "up to date" in ret[0].summary:
                LOGGER.warning(
                    "GitPython library has failed to push because we are "
                    "up to date already. How can it be? "
                )
            else:
                raise Warning(
                    f"Push has failed because: {ret[0].summary}.\n"
                    "Please verify that 'git push' works"
                )

        for tag in tags:
            try:
                self._origin.push(f"refs/tags/{tag}", o="ci.skip")
            except Exception:
                self._origin.push(
                    f"refs/tags/{tag}",
                )

    def pull(self):
        self._origin.pull()

    def commit(self, message, user, include=None):
        if include is not None:
            for file in include:
                self._be.index.add(file)
        author = git.Actor(user, user)

        self._be.index.commit(message=message, author=author)

    def root(self):
        return self._be.working_dir

    def status(self, tag):
        found_tag = None
        for _tag in self._be.tags:
            if _tag.name != tag:
                continue

            found_tag = _tag
            break

        return tuple(found_tag.commit.stats.files)

    def tags(self, branch=None, filter=None):
        cmd = ["--sort", "taggerdate"]
        if filter is not None:
            cmd.append("--list")
            cmd.append(filter)
        if branch is not None:
            cmd.append("--merged")
            cmd.append(branch)

        tags = self._be.git.tag(*cmd).split("\n")

        tags = tags[::-1]
        if len(tags) == 1 and tags[0] == "":
            tags.pop(0)

        return tags

    def in_detached_head(self):
        return self._be.head.is_detached

    def check_for_git_user_config(self):
        try:
            self._be.config_reader().get_value("user", "name")
            self._be.config_reader().get_value("user", "email")

            return None
        except (configparser.NoSectionError, configparser.NoOptionError):
            return "git user name or email configuration is missing, " "can't commit"

    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = f"Pending changes in {self.root()}."
            return err

        return None

    def check_for_outgoing_changes(self):
        if self.in_detached_head():
            err = f"Detached head in {self.root()}."
            return err

        branch_name = self._be.active_branch.name
        try:
            self._be.git.rev_parse("--verify", f"{self._origin.name}/{branch_name}")
        except Exception:
            err = (
                f"Branch {self._origin.name}/{branch_name} does not exist. "
                "Please push or set-upstream branch to "
                f"{self._origin.name}/{branch_name} of branch {branch_name}"
            )
            return err

        outgoing = tuple(
            self._be.iter_commits(f"{self._origin.name}/{branch_name}..{branch_name}")
        )

        if len(outgoing) > 0:
            err = f"Outgoing changes in {self.root()} from branch {branch_name} ({self._origin.name}/{branch_name}..{branch_name})"
            return err

        return None

    def checkout_branch(self):
        try:
            self.checkout(self.get_active_branch(raise_on_detached_head=False))
        except Exception:
            logging.info("Failed to get branch name. Trying to checkout to master")
            LOGGER.debug("Exception info: ", exc_info=True)
            self.checkout(rev="master")

        return self._be.active_branch.commit.hexsha

    def get_active_branch(self, raise_on_detached_head=True):
        if not self.in_detached_head():
            active_branch = self._be.active_branch.name
        else:
            if raise_on_detached_head:
                raise RuntimeError("Active branch cannot be found in detached head")

            out = self._be.git.branch("--contains", self._be.head.commit.hexsha)
            out = out.split("\n")[1:]
            active_branches = []
            for item in out:
                active_branches.append(item.strip())

            if len(active_branches) > 1:
                LOGGER.info(
                    "In detached head. Commit hash: "
                    f"{self._be.head.commit.hexsha} is "
                    f"related to multiple branches: {active_branches}. "
                    "Using the first one as the active branch"
                )

            active_branch = active_branches[0]

        return active_branch

    def checkout(self, rev=None, tag=None):
        if tag is not None:
            rev = tag

        self._be.git.checkout(rev)

    def last_user_changeset(self):
        init_hex = None
        for p in self._be.iter_commits():
            if p.author.name == VMN_USER_NAME:
                if p.message.startswith(INIT_COMMIT_MESSAGE):
                    init_hex = p.hexsha

                continue

            return p.hexsha

        return init_hex

    def remote(self):
        remote = tuple(self._origin.urls)[0]

        if os.path.isdir(remote):
            remote = os.path.relpath(remote, self.root())

        return remote

    def changeset(self, tag=None, short=False):
        if tag is None:
            return self._be.head.commit.hexsha

        found_tag = None
        for _tag in self._be.tags:
            if _tag.name != tag:
                continue

            found_tag = _tag
            break

        if found_tag:
            return found_tag.commit.hexsha

        return None

    def revert_vmn_changes(self, tags=[]):
        if self._be.active_branch.commit.author.name != VMN_USER_NAME:
            raise RuntimeError("BUG: Will not revert non-vmn commit.")

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

    def get_vmn_version_info(self, app_name, root=False):
        if root:
            regex = VMN_ROOT_TAG_REGEX
        else:
            regex = VMN_TAG_REGEX

        tag_formated_app_name = VersionControlBackend.get_tag_formatted_app_name(
            app_name
        )
        app_tags = self.tags(filter=(f"{tag_formated_app_name}_*"))
        cleaned_app_tag = None
        for tag in app_tags:
            match = re.search(regex, tag)
            if match is None:
                raise RuntimeError(f"Tag {tag} doesn't comply to vmn version format")

            gdict = match.groupdict()

            if gdict["app_name"] != app_name.replace("/", "-"):
                continue

            cleaned_app_tag = tag
            break

        if cleaned_app_tag is None:
            return None

        _, verinfo = self.get_vmn_tag_version_info(cleaned_app_tag)

        return verinfo

    def get_vmn_tag_version_info(self, tag_name):
        try:
            commit_tag_obj = self._be.commit(tag_name)
        except:
            # TODO: maybe log here?
            # Backward compatability code for vmn 0.3.9:
            try:
                tag_name = f"{tag_name}.0"
                commit_tag_obj = self._be.commit(tag_name)
            except:
                return tag_name, None

        if commit_tag_obj.author.name != VMN_USER_NAME:
            LOGGER.debug(f"Corrupted tag {tag_name}: author name is not vmn")
            return tag_name, None

        # TODO:: Check API commit version

        # safe_load discards any text before the YAML document (if present)
        tag_msg = yaml.safe_load(self._be.tag(f"refs/tags/{tag_name}").object.message)

        if type(tag_msg) is not dict and tag_msg.startswith("Automatic"):
            # Code from vmn 0.3.9
            # safe_load discards any text before the YAML document (if present)
            commit_msg = yaml.safe_load(self._be.commit(tag_name).message)

            if commit_msg is None or "stamping" not in commit_msg:
                return tag_name, None

            commit_msg["stamping"]["app"]["prerelease"] = "release"
            commit_msg["stamping"]["app"]["prerelease_count"] = {}

            return tag_name, commit_msg

        if not tag_msg:
            LOGGER.debug(f"Corrupted tag msg of tag {tag_name}")
            return tag_name, None

        all_tags = {}
        found = False
        # TODO: improve to iter_commits
        tags = self.tags(filter=f'{tag_name.split("_")[0].split("-")[0]}*')
        for tag in tags:
            if found and commit_tag_obj.hexsha != self._be.commit(tag).hexsha:
                break
            if commit_tag_obj.hexsha != self._be.commit(tag).hexsha:
                continue

            found = True

            tagd = VersionControlBackend.get_tag_properties(tag)
            tagd.update({"tag": tag})
            tagd["message"] = self._be.tag(f"refs/tags/{tag}").object.message

            all_tags[tagd["type"]] = tagd

            # TODO:: Check API commit version

        if "root" in all_tags:
            tag_msg["stamping"].update(
                yaml.safe_load(all_tags["root"]["message"])["stamping"]
            )

        return tag_name, tag_msg

    @staticmethod
    def clone(path, remote):
        git.Repo.clone_from(f"{remote}", f"{path}")


class HostState(object):
    @staticmethod
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            LOGGER.debug(
                f'Skipping "{path}" directory reason:\n',
                exc_info=True,
            )

            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remote("origin").urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception as exc:
            LOGGER.debug(f'Skipping "{path}" directory reason:\n', exc_info=True)
            return None
        finally:
            client.close()

        return hash, remote, "git"

    @staticmethod
    def get_actual_deps_state(paths, root):
        actual_deps_state = {}
        for path, lst in paths.items():
            repos = [name for name in lst if os.path.isdir(os.path.join(path, name))]

            for repo in repos:
                joined_path = os.path.join(path, repo)
                details = HostState.get_repo_details(joined_path)
                if details is None:
                    continue

                actual_deps_state[os.path.relpath(joined_path, root)] = {
                    "hash": details[0],
                    "remote": details[1],
                    "vcs_type": details[2],
                }

        return actual_deps_state


def get_versions_repo_path(root_path):
    versions_repo_path = os.getenv("VER_STAMP_VERSIONS_PATH", None)
    if versions_repo_path is not None:
        versions_repo_path = os.path.abspath(versions_repo_path)
    else:
        versions_repo_path = os.path.abspath(f"{root_path}/.vmn/versions")
        Path(versions_repo_path).mkdir(parents=True, exist_ok=True)

    return versions_repo_path


def get_client(path, revert=False, pull=False):
    be_type = None
    try:
        client = git.Repo(path, search_parent_directories=True)
        client.close()

        be_type = "git"
    except git.exc.InvalidGitRepositoryError:
        err = f"repository path: {path} is not a functional git " "or repository."
        return None, err

    be = None
    if be_type == "git":
        be = GitBackend(path, revert, pull)

    return be, None
