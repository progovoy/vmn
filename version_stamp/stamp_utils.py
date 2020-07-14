#!/usr/bin/env python3
import sys
import os
import hglib
import git
import logging
from pathlib import Path
from version_stamp import version as version_mod

INIT_COMMIT_MESSAGE = 'Initialized vmn tracking'


class VersionControlBackend(object):
    def __init__(self, type):
        self._type = type
        pass

    def __del__(self):
        pass

    def tag(self, tags, user):
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

    def tags(self):
        raise NotImplementedError()

    def check_for_pending_changes(self):
        raise NotImplementedError()

    def check_for_outgoing_changes(self):
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

    def type(self):
        return self._type


class MercurialBackend(VersionControlBackend):
    def __init__(self, repo_path, revert=False, pull=False):
        VersionControlBackend.__init__(self, 'mercurial')

        self._be = hglib.open(repo_path)

        if revert:
            self._be.revert([], all=True)
        if pull:
            self._be.pull(update=True)

    def __del__(self):
        self._be.close()

    def tag(self, tags, user):
        for tag in tags:
            self._be.tag(tag.encode(), user=user)

    def push(self, tags=()):
        self._be.push()

    def pull(self):
        self._be.pull(update=True)

    def commit(self, message, user, include=None):
        if include is not None:
            for file in include:
                self._be.add(file.encode())

        message = '{0}\n\n' \
                  'vmn version: {1}'.format(message, version_mod.version)

        self._be.commit(message=message, user=user)

    def root(self):
        return self._be.root().decode()

    def status(self, tag):
        status = self._be.status(change=tag)

        paths = []
        for item in status:
            paths.append(item[1].decode())

        return paths

    def tags(self):
        tags = []
        _tags = self._be.tags()

        for tag in _tags:
            tags.append(tag[0].decode())

        return tags

    def check_for_pending_changes(self):
        diff = self._be.diff()
        if diff != b'':
            err = 'Pending changes in {0}. Aborting'.format(self.root())
            return err

        return None

    def check_for_outgoing_changes(self):
        sum = self._be.summary()
        cur_branch = sum['branch'.encode('utf-8')].decode()
        out = self._be.outgoing(branch=cur_branch)
        if out:
            err = 'Outgoing changes in {0}. Aborting'.format(self.root())
            return err

        return None

    def checkout_branch(self):
        branch = self._be.branch()
        heads = self._be.heads()
        tip_changeset = None
        for head in heads:
            if head[3].decode() != branch:
                continue

            tip_changeset = head[1]
            break

        self._be.update(rev=tip_changeset)

        return tip_changeset

    def checkout(self, rev=None, tag=None):
        if tag is not None:
            _tags = self._be.tags()

            found = False
            changeset = self.changeset(short=True)
            for _tag in _tags:
                if _tag[0].decode() == tag:
                    self._be.update(rev=_tag[1])
                    found = True

            if not found:
                raise RuntimeError('{0} tag not found'.format(tag))

            self._be.update(rev=int(changeset) + 1)
        else:
            self._be.update(rev=rev)

    def remote(self):
        remotes = []
        for k, remote in self._be.paths().items():
            remotes.append(remote.decode('utf-8'))

        remote = remotes[0]
        if os.path.isdir(remote):
            remote = os.path.relpath(remote, self.root())

        return remote

    def last_user_changeset(self):
        rev = self._be.tip()
        while rev.author.decode() == 'vmn':
            if rev.desc.decode().startswith(INIT_COMMIT_MESSAGE):
                break

            rev = self._be.parents(rev[1].decode())[0]

        return rev[1].decode()

    def changeset(self, short=False):
        tip = self._be.tip()
        if short:
            return self._be.tip()[0].decode()

        return tip[1].decode()

    def revert_vmn_changes(self, tags):
        # TODO: implement
        return

    @staticmethod
    def clone(path, remote):
        hglib.clone(
            '{0}'.format(remote),
            '{0}'.format(path)
        )


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

    def tag(self, tags, user):
        for tag in tags:
            self._be.create_tag(
                tag,
                message='Automatic tag "{0}"'.format(tag)
            )

    def push(self, tags=()):
        self._origin.push()
        for tag in tags:
            self._origin.push(tag)

    def pull(self):
        self._origin.pull()

    def commit(self, message, user, include=None):
        if include is not None:
            for file in include:
                self._be.index.add(file)
        author = git.Actor(user, user)

        message = '{0}\n\n' \
                  'vmn version: {1}'.format(message, version_mod.version)

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

    def tags(self):
        tags = []
        _tags = self._be.tags

        for tag in _tags:
            tags.append(tag.name)

        return tags[::-1]

    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = 'Pending changes in {0}.'.format(self.root())
            return err

        return None

    def check_for_outgoing_changes(self):
        for branch in self._be.branches:
            outgoing = tuple(self._be.iter_commits(
                'origin/{0}..{0}'.format(branch))
            )

            if len(outgoing) > 0:
                err = 'Outgoing changes in {0}'.format(self.root())
                return err

        return None

    def checkout_branch(self):
        try:
            self.checkout(self._be.active_branch.name)
        except:
            self.checkout(rev='master')

        return self._be.active_branch.commit.hexsha

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
    if be_type == 'mercurial':
        be = MercurialBackend(path, revert, pull)
    elif be_type == 'git':
        be = GitBackend(path, revert, pull)

    return be, None
