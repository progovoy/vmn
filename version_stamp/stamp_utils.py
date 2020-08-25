#!/usr/bin/env python3
import sys
import os
import hglib
import git
import logging
import yaml
from pathlib import Path
import re

INIT_COMMIT_MESSAGE = 'Initialized vmn tracking'
MOVING_COMMIT_PREFIX = '_-'


class VersionControlBackend(object):
    def __init__(self, type):
        self._type = type
        pass

    def __del__(self):
        pass

    def tag(self, tags, user, force=False):
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

    def tags(self, branch=None):
        raise NotImplementedError()

    def check_for_pending_changes(self):
        raise NotImplementedError()

    def check_for_outgoing_changes(self, skip_detached_check=False):
        raise NotImplementedError()

    def checkout_branch(self):
        raise NotImplementedError()

    def checkout(self, rev=None, tag=None):
        raise NotImplementedError()

    def parents(self):
        raise NotImplementedError()

    def remote(self):
        raise NotImplementedError()

    def changeset(self, short=False):
        raise NotImplementedError()

    def revert_vmn_changes(self, tags):
        raise NotImplementedError()

    def get_vmn_version_info(self, tag_name):
        raise NotImplementedError()

    def get_active_branch(self, raise_on_detached_head=True):
        raise NotImplementedError()

    def type(self):
        return self._type

    @staticmethod
    def get_tag_name(app_name, version=None):
        app_name = app_name.replace('/', '-')

        if version is None:
            return '{0}'.format(app_name)
        else:
            return '{0}_{1}'.format(app_name, version)

    @staticmethod
    def get_moving_tag_name(app_name, branch):
        app_name = app_name.replace('/', '-')
        return '{0}latest-{1}-_-{2}-'.format(
            MOVING_COMMIT_PREFIX,
            branch,
            app_name
        )

    @staticmethod
    def get_moving_tag_properties(tag_name):
        groups = re.search(
            r'{0}latest\-(.+)\-_\-(.+)\-'.format(
                MOVING_COMMIT_PREFIX), tag_name
        ).groups()

        if len(groups) != 2:
            return None, None

        branch = groups[0]
        app_name = groups[1].replace('-', '/')

        return branch, app_name


class GitBackend(VersionControlBackend):
    def __init__(self, repo_path, revert=False, pull=False):
        VersionControlBackend.__init__(self, 'git')

        self._be = git.Repo(repo_path, search_parent_directories=True)
        self._origin = self._be.remote(name='origin')

        if revert:
            self._be.head.reset(working_tree=True)
        if pull:
            self.pull()

    def __del__(self):
        self._be.close()

    def tag(self, tags, user, force=False):
        for tag in tags:
            self._be.create_tag(
                tag,
                message='Automatic tag "{0}"'.format(tag),
                force=force
            )

    def push(self, tags=()):
        try:
            ret = self._origin.push(o='ci.skip')
        except git.GitCommandError:
            ret = self._origin.push()

        if ret[0].old_commit is None:
            if 'up to date' in ret[0].summary:
                logging.getLogger().warning(
                    'GitPython library has failed to push because we are '
                    'up to date already. How can it be? '
                )
            else:
                raise Warning(
                    'Push has failed: {0}'.format(
                        ret[0].summary
                    )
                )

        for tag in tags:
            try:
                self._origin.push(tag, o='ci.skip')
            except git.GitCommandError:
                self._origin.push(tag)

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

    def tags(self, branch=None):
        if branch is None:
            tags = self._be.git.tag(
                '--sort',
                'creatordate',
            ).split('\n')
        else:
            tags = self._be.git.tag(
                '--sort',
                'creatordate',
                '--merged',
                branch
            ).split('\n')

        return tags[::-1]

    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = 'Pending changes in {0}.'.format(self.root())
            return err

        return None

    def check_for_outgoing_changes(self, skip_detached_check=False):
        if self._be.head.is_detached:
            if skip_detached_check:
                return None

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
            self.checkout(self._be.active_branch.name)
        except:
            self.checkout(rev='master')

        return self._be.active_branch.commit.hexsha

    def get_active_branch(self, raise_on_detached_head=True):
        if not self._be.head.is_detached:
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
                logging.getLogger().info(
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
        for p in self._be.iter_commits():
            if p.author.name == 'vmn':
                if not p.message.startswith(INIT_COMMIT_MESSAGE):
                    continue

            return p.hexsha

    def remote(self):
        remote = tuple(self._origin.urls)[0]

        if os.path.isdir(remote):
            remote = os.path.relpath(remote, self.root())

        return remote

    def changeset(self, short=False):
        return self._be.head.commit.hexsha

    def revert_vmn_changes(self, tags):
        if self._be.active_branch.commit.author.name != 'vmn':
            raise RuntimeError('BUG: Will not revert non-vmn commit.')

        self._be.git.reset('--hard', 'HEAD~1')
        for tag in tags:
            try:
                self._be.delete_tag(tag)
            except Exception:
                logging.getLogger().exception(
                    'Failed to remove tag {0}'.format(tag)
                )

                continue

    def get_vmn_version_info(self, tag_name):
        commit_tag_obj = None
        try:
            commit_tag_obj = self._be.commit(tag_name)
        except:
            if not tag_name.startswith(MOVING_COMMIT_PREFIX):
                return None

            branch, app_name = \
                VersionControlBackend.get_moving_tag_properties(tag_name)

            if branch is None:
                return None

            for tag in self.tags(branch=branch):
                if not tag.startswith(app_name):
                    continue

                commit_tag_obj = self._be.commit(tag)
                if commit_tag_obj.author.name != 'vmn':
                    continue

                tag_name = tag
                break

        if commit_tag_obj is None:
            return None

        if commit_tag_obj.author.name != 'vmn':
            return None

        # TODO:: Check API commit version

        return yaml.safe_load(
            self._be.commit(tag_name).message
        )

    @staticmethod
    def clone(path, remote):
        git.Repo().clone_from(
            '{0}'.format(remote),
            '{0}'.format(path)
        )


class HostState(object):
    @staticmethod
    def _get_mercurial_changeset(path):
        try:
            client = hglib.open(path)
        except hglib.error.ServerError as exc:
            logging.getLogger().info(
                'Skipping "{0}" directory '
                'reason:\n{1}\n'.format(path, exc)
            )
            return None

        revision = client.parents()
        if revision is None:
            revision = client.log()

            if revision is None:
                client.close()
                return None

        changeset = revision[0][1]
        try:
            remotes = []
            for k, remote in client.paths().items():
                remotes.append(remote.decode('utf-8'))

            if os.path.isdir(remotes[0]):
                remote = os.path.relpath(remotes[0], client.root().decode())
            else:
                remote = remotes[0]

        except Exception as exc:
            logging.getLogger().info(
                'Skipping "{0}" directory reason:\n{1}\n'.format(
                    path, exc)
            )
            client.close()
            return None

        client.close()
        return changeset.decode('utf-8'), remote

    @staticmethod
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            ret = HostState._get_mercurial_changeset(path)
            if ret is None:
                logging.getLogger().info(
                    'Skipping "{0}" directory reason:\n{1}\n'.format(
                        path, exc)
                )

                return None

            return (*ret, 'mercurial')

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remote('origin').urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception as exc:
            logging.getLogger().info(
                'Skipping "{0}" directory reason:\n{1}\n'.format(
                    path, exc)
            )
            return None
        finally:
            client.close()

        return hash, remote, 'git'

    @staticmethod
    def get_user_repo_details(paths, root):
        user_repos_details = {}
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

                user_repos_details[os.path.relpath(joined_path, root)] = {
                    'hash': details[0],
                    'remote': details[1],
                    'vcs_type': details[2],
                }

        return user_repos_details


def init_stamp_logger():
    LOGGER = logging.getLogger('vmn')
    LOGGER.setLevel(logging.DEBUG)
    format = '[%(levelname)s] %(message)s'

    formatter = logging.Formatter(format, '%Y-%m-%d %H:%M:%S')

    cons_handler = logging.StreamHandler(sys.stdout)
    cons_handler.setFormatter(formatter)
    LOGGER.addHandler(cons_handler)

    return LOGGER


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
        try:
            client = hglib.open(path)
            client.close()

            be_type = 'mercurial'
        except hglib.error.ServerError:
            err = 'repository path: {0} is not a functional git ' \
                  'or mercurial repository.'.format(path)
            return None, err

    be = None
    if be_type == 'git':
        be = GitBackend(path, revert, pull)

    return be, None
