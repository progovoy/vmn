#!/usr/bin/env python3
import sys
import os
import git
import logging
from pathlib import Path
import re
import time

import yaml
from packaging import version as pversion
import configparser

INIT_COMMIT_MESSAGE = 'Initialized vmn tracking'

VMN_VERSION_FORMAT = \
    "{major}.{minor}.{patch}[.{hotfix}][-{prerelease}]"

SEMVER_REGEX = \
    '^(?P<major>0|[1-9]\d*)\.' \
    '(?P<minor>0|[1-9]\d*)\.' \
    '(?P<patch>0|[1-9]\d*)' \
    '(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?' \
    '(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'
# Regex for matching versions stamped by vmn
VMN_REGEX = \
    '^(?P<major>0|[1-9]\d*)\.' \
    '(?P<minor>0|[1-9]\d*)\.' \
    '(?P<patch>0|[1-9]\d*)' \
    '(?:\.(?P<hotfix>0|[1-9]\d*))?' \
    '(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?' \
    '(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?' \
    '(?:-(?P<releasenotes>(?:rn\.[1-9]\d*))+)?$'
#TODO: create an abstraction layer on top of tag names versus the actual Semver versions
VMN_TAG_REGEX = \
    '^(?P<app_name>[^\/]+)_(?P<major>0|[1-9]\d*)\.' \
    '(?P<minor>0|[1-9]\d*)\.' \
    '(?P<patch>0|[1-9]\d*)' \
    '(?:\.(?P<hotfix>0|[1-9]\d*))?' \
    '(?:-(?P<prerelease>(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?' \
    '(?:\+(?P<buildmetadata>[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?' \
    '(?:-(?P<releasenotes>(?:rn\.[1-9]\d*))+)?$'

VMN_ROOT_TAG_REGEX = '(?P<app_name>[^\/]+)_(?P<version>0|[1-9]\d*)$'

VMN_TEMPLATE_REGEX = \
    '^(?:\[(?P<major_template>[^\{\}]*\{major\}[^\{\}]*)\])?' \
    '(?:\[(?P<minor_template>[^\{\}]*\{minor\}[^\{\}]*)\])?' \
    '(?:\[(?P<patch_template>[^\{\}]*\{patch\}[^\{\}]*)\])?' \
    '(?:\[(?P<hotfix_template>[^\{\}]*\{hotfix\}[^\{\}]*)\])?' \
    '(?:\[(?P<prerelease_template>[^\{\}]*\{prerelease\}[^\{\}]*)\])?' \
    '(?:\[(?P<buildmetadata_template>[^\{\}]*\{buildmetadata\}[^\{\}]*)\])?' \
    '(?:\[(?P<releasenotes_template>[^\{\}]*\{releasenotes\}[^\{\}]*)\])?$'

VMN_USER_NAME = 'vmn'
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
    format = '[%(levelname)s] %(message)s'

    formatter = logging.Formatter(format, '%Y-%m-%d %H:%M:%S')

    cons_handler = logging.StreamHandler(sys.stdout)
    cons_handler.setFormatter(formatter)
    LOGGER.addHandler(cons_handler)

    return LOGGER


class VersionControlBackend(object):
    def __init__(self, type):
        self._type = type
        pass

    def __del__(self):
        pass

    def tag(self, tags, messages, ref='HEAD'):
        raise NotImplementedError()

    def push(self, tags=()):
        raise NotImplementedError()

    def pull(self):
        raise NotImplementedError()

    def commit(self, message, user, include=None):
        raise NotImplementedError()

    def root(self):
        raise NotImplementedError()

    def status(self, tag):
        raise NotImplementedError()

    def tags(self, branch=None, filter=None):
        raise NotImplementedError()

    def in_detached_head(self):
        raise NotImplementedError()

    def check_for_pending_changes(self):
        raise NotImplementedError()

    def check_for_outgoing_changes(self):
        raise NotImplementedError()

    def checkout_branch(self):
        raise NotImplementedError()

    def checkout(self, rev=None, tag=None):
        raise NotImplementedError()

    def remote(self):
        raise NotImplementedError()

    def changeset(self, short=False):
        raise NotImplementedError()

    def revert_vmn_changes(self, tags):
        raise NotImplementedError()

    def get_active_branch(self, raise_on_detached_head=True):
        raise NotImplementedError()

    def type(self):
        return self._type

    @staticmethod
    def get_tag_formatted_app_name(app_name, version=None):
        app_name = app_name.replace('/', '-')

        if version is None:
            return '{0}'.format(app_name)
        else:
            return '{0}_{1}'.format(app_name, version)

    @staticmethod
    def get_tag_properties(vmn_tag):
        ret = {
            'app_name': None,
            'type': 'version',
            'version': None,
            'root_version': None,
            'hotfix': None,
            'prerelease': None,
            'buildmetadata': None,
            'releasenotes': None,
        }

        match = re.search(
            VMN_ROOT_TAG_REGEX,
            vmn_tag
        )
        if match is not None:
            gdict = match.groupdict()
            if gdict['version'] is not None:
                int(gdict['version'])
                ret['root_version'] = gdict['version']
                ret['type'] = 'root'

            return ret

        match = re.search(
            VMN_TAG_REGEX,
            vmn_tag
        )
        if match is None:
            raise RuntimeError(
                f"Tag {vmn_tag} doesn't comply to vmn version format"
            )

        gdict = match.groupdict()
        ret['app_name'] = gdict['app_name'].replace('-', '/')
        ret['version'] = f'{gdict["major"]}.{gdict["minor"]}.{gdict["patch"]}'
        ret['hotfix'] = '0'

        if gdict['hotfix'] is not None:
            ret['hotfix'] = gdict['hotfix']

        if gdict['prerelease'] is not None:
            ret['prerelease'] = gdict['prerelease']
            ret['type'] = 'prerelease'

        if gdict['buildmetadata'] is not None:
            ret['buildmetadata'] = gdict['buildmetadata']
            ret['type'] = 'buildmetadata'

        if gdict['releasenotes'] is not None:
            ret['releasenotes'] = gdict['releasenotes']
            ret['type'] = 'releasenotes'

        return ret

    @staticmethod
    def get_utemplate_formatted_version(raw_vmn_version, template):
        match = re.search(
            VMN_REGEX,
            raw_vmn_version
        )

        gdict = match.groupdict()
        if gdict['hotfix'] == '0':
            gdict['hotfix'] = None

        octats = (
            'major', 'minor', 'patch', 'hotfix', 'prerelease',
            'buildmetadata', 'releasenotes'
        )

        formatted_version = ''
        for octat in octats:
            if gdict[octat] is None:
                continue

            if f'{octat}_template' in template and template[f'{octat}_template'] is not None:
                d = {octat: gdict[octat]}
                formatted_version = \
                    f"{formatted_version}" \
                    f"{template[f'{octat}_template'].format(**d)}"

        return formatted_version


class GitBackend(VersionControlBackend):
    def __init__(self, repo_path, revert=False, pull=False):
        VersionControlBackend.__init__(self, 'git')

        self._be = git.Repo(repo_path, search_parent_directories=True)
        self._origin = self._be.remote(name='origin')

        if revert:
            self._be.head.reset(working_tree=True)
        if pull:
            self.pull()

        self._be.git.fetch('--tags')

    def __del__(self):
        self._be.close()

    def is_tracked(self, path):
        return path in [item.replace('/', os.sep) for item in self._be.untracked_files]

    def tag(self, tags, messages, ref='HEAD'):
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
                'refs/heads/{0}'.format(self.get_active_branch()),
                o='ci.skip'
            )
        except Exception:
            ret = self._origin.push(
                'refs/heads/{0}'.format(self.get_active_branch()),
            )

        if ret[0].old_commit is None:
            if 'up to date' in ret[0].summary:
                LOGGER.warning(
                    'GitPython library has failed to push because we are '
                    'up to date already. How can it be? '
                )
            else:
                raise Warning(
                    'Push has failed: {0}\n'
                    'please verify the next command works:\n'
                    'git push'.format(
                        ret[0].summary
                    )
                )

        for tag in tags:
            try:
                self._origin.push(
                    'refs/tags/{0}'.format(tag),
                    o='ci.skip'
                )
            except Exception:
                self._origin.push(
                    'refs/tags/{0}'.format(tag),
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
        cmd = ['--sort', 'taggerdate']
        if filter is not None:
            cmd.append('--list')
            cmd.append(filter)
        if branch is not None:
            cmd.append('--merged')
            cmd.append(branch)

        tags = self._be.git.tag(
            *cmd
        ).split('\n')

        tags = tags[::-1]
        if len(tags) == 1 and tags[0] == '':
            tags.pop(0)

        return tags

    def in_detached_head(self):
        return self._be.head.is_detached

    def check_for_git_user_config(self):
        try:
            self._be.config_reader().get_value('user', 'name')
            self._be.config_reader().get_value('user', 'email')

            return None
        except (configparser.NoSectionError, configparser.NoOptionError):
            return "git user name or email configuration is missing, " \
                   "can't commit"

    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = 'Pending changes in {0}.'.format(self.root())
            return err

        return None

    def check_for_outgoing_changes(self):
        if self.in_detached_head():
            err = 'Detached head in {0}.'.format(self.root())
            return err

        branch_name = self._be.active_branch.name
        try:
            self._be.git.rev_parse(
                '--verify', '{0}/{1}'.format(
                    self._origin.name, branch_name
                )
            )
        except Exception:
            err = 'Branch {0}/{1} does not exist. ' \
                  'Please push or set-upstream branch to ' \
                  '{0}/{1} of branch {1}'.format(
                      self._origin.name, branch_name)
            return err

        outgoing = tuple(self._be.iter_commits(
            '{0}/{1}..{1}'.format(self._origin.name, branch_name))
        )

        if len(outgoing) > 0:
            err = 'Outgoing changes in {0} from branch {1}'.format(
                self.root(), branch_name
            )
            return err

        return None

    def checkout_branch(self):
        try:
            self.checkout(self.get_active_branch(raise_on_detached_head=False))
        except Exception:
            logging.exception(
                'Failed to get branch name. Trying to checkout to master'
            )
            self.checkout(rev='master')

        return self._be.active_branch.commit.hexsha

    def get_active_branch(self, raise_on_detached_head=True):
        if not self.in_detached_head():
            active_branch = self._be.active_branch.name
        else:
            if raise_on_detached_head:
                raise RuntimeError(
                    'Active branch cannot be found in detached head'
                )

            out = self._be.git.branch(
                '--contains',
                self._be.head.commit.hexsha
            )
            out = out.split('\n')[1:]
            active_branches = []
            for item in out:
                active_branches.append(item.strip())

            if len(active_branches) > 1:
                LOGGER.info(
                    'In detached head. Commit hash: {0} is '
                    'related to multiple branches: {1}. Using the first '
                    'one as the active branch'.format(
                        self._be.head.commit.hexsha,
                        active_branches
                    )
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

    def revert_vmn_changes(self, tags):
        if self._be.active_branch.commit.author.name != VMN_USER_NAME:
            raise RuntimeError('BUG: Will not revert non-vmn commit.')

        self._be.git.reset('--hard', 'HEAD~1')
        for tag in tags:
            try:
                self._be.delete_tag(tag)
            except Exception:
                LOGGER.exception(
                    'Failed to remove tag {0}'.format(tag)
                )

                continue

        try:
            self._be.git.fetch('--tags')
        except Exception:
            LOGGER.exception(
                'Failed to fetch tags'
            )

    def get_vmn_version_info(self, app_name, root=False):
        if root:
            regex = VMN_ROOT_TAG_REGEX
        else:
            regex = VMN_TAG_REGEX

        tag_formated_app_name = VersionControlBackend.get_tag_formatted_app_name(
            app_name
        )
        app_tags = self.tags(filter=(f'{tag_formated_app_name}_*'))
        cleaned_app_tags = []
        for tag in app_tags:
            match = re.search(
                regex,
                tag
            )
            if match is None:
                raise RuntimeError(
                    f"Tag {tag} doesn't comply to vmn version format"
                )

            gdict = match.groupdict()

            if gdict['app_name'] != app_name.replace('/', '-'):
                continue

            cleaned_app_tags.append(tag)

        if not cleaned_app_tags:
            return None

        return self.get_vmn_tag_version_info(cleaned_app_tags[0])

    def get_vmn_tag_version_info(self, tag_name):
        try:
            commit_tag_obj = self._be.commit(tag_name)
        except:
            return None

        if commit_tag_obj.author.name != VMN_USER_NAME:
            raise RuntimeError(f'Corrupted tag {tag_name}: author name is not vmn')

        # TODO:: Check API commit version
        # TODO: check if newer vmn has stamped here

        # safe_load discards any text before the YAML document (if present)
        tag_msg = yaml.safe_load(
            self._be.tag(f'refs/tags/{tag_name}').object.message
        )
        if not tag_msg:
            raise RuntimeError(f'Corrupted tag msg of tag {tag_name}')

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
            tagd.update({'tag': tag})
            tagd['message'] = \
                self._be.tag(f'refs/tags/{tag}').object.message

            all_tags[tagd['type']] = tagd

            # TODO:: Check API commit version

        if 'root' in all_tags:
            tag_msg['stamping'].update(
                yaml.safe_load(all_tags['root']['message'])['stamping']
            )

        return tag_msg

    @staticmethod
    def clone(path, remote):
        git.Repo.clone_from(
            '{0}'.format(remote),
            '{0}'.format(path)
        )


class HostState(object):
    @staticmethod
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            LOGGER.debug(
                'Skipping "{0}" directory reason:\n{1}\n'.format(
                    path, exc), exc_info=exc
            )

            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remote('origin').urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception as exc:
            LOGGER.debug(
                'Skipping "{0}" directory reason:\n'.format(
                    path), exc_info=exc
            )
            return None
        finally:
            client.close()

        return hash, remote, 'git'

    @staticmethod
    def get_actual_deps_state(paths, root):
        actual_deps_state = {}
        for path, lst in paths.items():
            repos = [
                name for name in lst
                if os.path.isdir(os.path.join(path, name))
            ]

            for repo in repos:
                joined_path = os.path.join(path, repo)
                details = HostState.get_repo_details(joined_path)
                if details is None:
                    continue

                actual_deps_state[os.path.relpath(joined_path, root)] = {
                    'hash': details[0],
                    'remote': details[1],
                    'vcs_type': details[2],
                }

        return actual_deps_state


def get_versions_repo_path(root_path):
    versions_repo_path = os.getenv('VER_STAMP_VERSIONS_PATH', None)
    if versions_repo_path is not None:
        versions_repo_path = os.path.abspath(versions_repo_path)
    else:
        versions_repo_path = os.path.abspath(
            '{0}/.vmn/versions'.format(root_path)
        )
        Path(versions_repo_path).mkdir(parents=True, exist_ok=True)

    return versions_repo_path


def get_client(path, revert=False, pull=False):
    be_type = None
    try:
        client = git.Repo(path, search_parent_directories=True)
        client.close()

        be_type = 'git'
    except git.exc.InvalidGitRepositoryError:
        err = 'repository path: {0} is not a functional git ' \
              'or repository.'.format(path)
        return None, err

    be = None
    if be_type == 'git':
        be = GitBackend(path, revert, pull)

    return be, None
