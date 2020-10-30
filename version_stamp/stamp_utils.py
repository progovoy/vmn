#!/usr/bin/env python3
import sys
import os
import git
import yaml
import logging
from pathlib import Path
import re
from packaging import version as pversion

INIT_COMMIT_MESSAGE = 'Initialized vmn tracking'
MOVING_COMMIT_PREFIX = '_-'
LOGGER = None

def init_stamp_logger():
    global LOGGER

    LOGGER = logging.getLogger('vmn')
    LOGGER.setLevel(logging.DEBUG)
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

    def get_vmn_version_info(self, tag_name=None, app_name=None):
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
    def get_tag_properties(tag_name, root=False):
        try:
            if not root:
                groups = re.search(
                    r'(.+)_(\d+\.\d+\.\d+\.\d+)$',
                    tag_name
                ).groups()
            else:
                groups = re.search(
                    r'(.+)_(\d+)$',
                    tag_name
                ).groups()
        except:
            return None, None

        if len(groups) != 2:
            return None, None

        app_name = groups[0].replace('-', '/')
        version = groups[1]

        return app_name, version


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
                    'Push has failed: {0}'.format(
                        ret[0].summary
                    )
                )

        for tag in tags:
            try:
                self._origin.push(
                    'refs/tags/{0}'.format(tag),
                    force=True,
                    o='ci.skip'
                )
            except Exception:
                self._origin.push(
                    'refs/tags/{0}'.format(tag),
                    force=True
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
        cmd = ['--sort', 'creatordate']
        if filter is not None:
            cmd.append('--list')
            cmd.append(filter)
        if branch is not None:
            cmd.append('--merged')
            cmd.append(branch)

        tags = self._be.git.tag(
            *cmd
        ).split('\n')

        return tags[::-1]

    def in_detached_head(self):
        return self._be.head.is_detached

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

    def get_vmn_version_info(
            self,
            tag_name=None,
            app_name=None,
            root_app_name=None
    ):
        if tag_name is None and app_name is None and root_app_name is None:
            return None

        commit_tag_obj = None
        if tag_name is not None:
            try:
                commit_tag_obj = self._be.commit(tag_name)
            except:
                return None
        elif app_name is not None or root_app_name is not None:
            used_app_name = app_name
            root = False
            if root_app_name is not None:
                used_app_name = root_app_name
                root = True

            try:
                branch = self.get_active_branch()
            except:
                branch = None

            max_version = '0.0.0.0'
            for tag in self.tags(branch=branch):
                _app_name, version = VersionControlBackend.get_tag_properties(
                    tag, root=root
                )
                if version is None:
                    continue

                if _app_name != used_app_name:
                    continue

                _commit_tag_obj = self._be.commit(tag)
                if _commit_tag_obj.author.name != 'vmn':
                    continue

                if pversion.parse(max_version) < pversion.parse(version):
                    max_version = version
                    tag_name = tag
                    commit_tag_obj = _commit_tag_obj

        if commit_tag_obj is None:
            return None

        if commit_tag_obj.author.name != 'vmn':
            return None

        # TODO:: Check API commit version

        commit_msg = yaml.safe_load(
            self._be.commit(tag_name).message
        )

        if 'stamping' not in commit_msg:
            return None

        return commit_msg

    @staticmethod
    def clone(path, remote):
        git.Repo().clone_from(
            '{0}'.format(remote),
            '{0}'.format(path)
        )


class HostState(object):
    @staticmethod
    def get_repo_details(path):
        try:
            client = git.Repo(path, search_parent_directories=True)
        except git.exc.InvalidGitRepositoryError as exc:
            LOGGER.info(
                'Skipping "{0}" directory reason:\n{1}\n'.format(
                    path, exc)
            )

            return None

        try:
            hash = client.head.commit.hexsha
            remote = tuple(client.remote('origin').urls)[0]
            if os.path.isdir(remote):
                remote = os.path.relpath(remote, client.working_dir)
        except Exception as exc:
            LOGGER.info(
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
