#!/usr/bin/env python3
import argparse
import copy
import sys
import os
import hglib
import git
import logging
import importlib.machinery
import types
import re
from multiprocessing import Pool

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)
format = '[%(asctime)s.%(msecs)03d] [%(name)s] [%(levelname)s] ' \
         '%(message)s'

formatter = logging.Formatter(format, '%Y-%m-%d %H:%M:%S')

cons_handler = logging.StreamHandler(sys.stdout)
cons_handler.setFormatter(formatter)
LOGGER.addHandler(cons_handler)


def goto_version(repos_path, app_name, app_version, git_remote,
                 mercurial_remote):
    if app_name is None:
        _goto_version(
            repos_path,
            {'git': git_remote, 'mercurial': mercurial_remote}
        )
        return

    versions_client = hglib.open('{0}/{1}'.format(repos_path, 'versions'))
    versions_client.revert([], all=True)
    try:
        versions_client.pull(update=True, branch='default')
    except Exception as exc:
        LOGGER.exception(
            'Failed to pull from versions at {0}'.format(repos_path)
        )

        raise exc

    root = versions_client.root().decode()
    tags = versions_client.tags()
    tip_app_tag = None
    tip_app_tag_index = None
    app_tag = None
    app_tag_index = None

    for idx, tag in enumerate(tags):
        if not tag[0].decode().startswith('{0}_'.format(app_name)):
            continue

        if tip_app_tag is None:
            tip_app_tag = tag
            tip_app_tag_index = idx

        tag_ver = tag[0].decode().split('{0}_'.format(app_name))[1]
        if app_version == tag_ver:
            app_tag = tag
            app_tag_index = idx
            break

    if app_tag is None:
        LOGGER.info('Tag with app: {0} with version: {1} was not found'.format(
            app_name, app_version
        ))
        return 1

    app_ver_path = None
    paths = versions_client.status(change=tip_app_tag[0])
    for path in paths:
        if not path[1].decode().endswith('/main_version.py'):
            continue

        # Retrieve the tag of the service
        app_tag = tags[app_tag_index - 1]
        res = re.search('(.+)_(.+)', app_tag[0].decode())
        app_name = res.groups()[0]
        app_version = res.groups()[1]

        main_ver_path = '{0}/{1}'.format(root, path[1].decode())

        loader = importlib.machinery.SourceFileLoader(
            'main_version', main_ver_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        services = mod_ver.services
        app_ver_path = '{0}/{1}'.format(root, services[app_name]['path'])

        break

    for path in paths:
        if app_ver_path is None:
            if not path[1].decode().endswith('/version.py'):
                continue

            app_ver_path = '{0}/{1}'.format(root, path[1].decode())

        app_ver_dir_path = os.path.dirname(app_ver_path)

        loader = importlib.machinery.SourceFileLoader(
            'version', app_ver_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        current_changesets = mod_ver.changesets

        if tip_app_tag_index == app_tag_index:
            _goto_version(
                repos_path,
                {'git': git_remote, 'mercurial': mercurial_remote},
                current_changesets,
            )
            return 0

        app_hist_ver_path = '{0}/{1}'.format(
            app_ver_dir_path, '_version_history.py')

        if not os.path.isfile(app_hist_ver_path):
            LOGGER.info(
                'Missing history version file: {0}'.format(app_hist_ver_path)
            )
            return 1

        loader = importlib.machinery.SourceFileLoader(
            '_version_history', app_hist_ver_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        hist_changesets = mod_ver.changesets

        if app_version not in hist_changesets:
            LOGGER.info(
                'App: {0} with version: {1} was not found in hist file'.format(
                    app_name, app_version))
            return 1

        _goto_version(
            repos_path,
            {'git': git_remote, 'mercurial': mercurial_remote},
            hist_changesets[app_version],
        )
        return 0

    LOGGER.info('App: {0} with version: {1} was not found'.format(
        app_name, app_version
    ))
    return 1


def _mercurial_pull(cur_path, repo, changesets):
    client = None
    try:
        client = hglib.open(cur_path)
        diff = client.diff()
        if diff != b'':
            err = 'Pending changes in {0}. Aborting'.format(cur_path)
            LOGGER.info('{0}. Will abort operation'.format(err))
            return {'repo': repo, 'status': 1, 'description': err}

    except hglib.error.ServerError as exc:
        LOGGER.exception('Skipping "{0}" directory reason:\n{1}\n'.format(
            cur_path, exc)
        )
        return {'repo': repo, 'status': 0, 'description': None}
    finally:
        if client is not None:
            client.close()

    try:
        sum = client.summary()
        cur_branch = sum['branch'.encode('utf-8')].decode()
        out = client.outgoing(branch=cur_branch)
        if out:
            err = 'Outgoing changes in {0}. Aborting'.format(cur_path)
            LOGGER.info('{0}. Will abort operation'.format(err))
            return {'repo': repo, 'status': 1, 'description': err}

        LOGGER.info('Pulling from {0}'.format(repo))
        client.pull(update=True)

        # If no changesets were given - update to default
        if changesets is None:
            heads = client.heads()
            tip_changeset = None
            for head in heads:
                if head[3] != b'default':
                    continue

                tip_changeset = head[1]
                break

            client.update(rev=tip_changeset)
            LOGGER.info('Updated {0} to {1} tip'.format(repo, tip_changeset))
        elif repo in changesets:
            client.update(rev=changesets[repo]['hash'])

            LOGGER.info('Updated {0} to {1}'.format(
                repo, changesets[repo]['hash']))

        return {'repo': repo, 'status': 0, 'description': None}
    except Exception as exc:
        LOGGER.exception(
            'Aborting directory {0} '
            'PLEASE FIX. Reason:\n{1}\n'.format(cur_path, exc)
        )

        return {'repo': repo, 'status': 1, 'description': None}
    finally:
        client.close()


def _git_pull(cur_path, repo, changesets):
    client = None
    try:
        client = git.Repo(cur_path)
        if client.is_dirty():
            err = 'Pending changes in {0}. Aborting'.format(cur_path)
            LOGGER.info('{0}. Will abort operation'.format(err))

            return {'repo': repo, 'status': 1, 'description': err}

    except Exception as exc:
        LOGGER.exception('Skipping "{0}" directory reason:\n{1}\n'.format(
            cur_path, exc)
        )
        return {'repo': repo, 'status': 0, 'description': None}
    finally:
        if client is not None:
            client.close()

    try:
        cur_branch = client.active_branch
    except TypeError:
        err = 'Failed to retrieve active_branch. Probably in detached ' \
              'head in {0}'.format(cur_path)
        LOGGER.exception('{0}'.format(err))

        if changesets is not None:
            return {'repo': repo, 'status': 1, 'description': err}
        else:
            cur_branch = 'master'
            client.git.checkout(cur_branch)
    finally:
        client.close()

    try:
        outgoing = list(client.iter_commits(
            'origin/{0}..{0}'.format(cur_branch))
        )

        if len(outgoing) > 0:
            err = 'Outgoing changes in {0}. Aborting'.format(cur_path)
            LOGGER.info('{0}. Will abort operation'.format(err))
            return {'repo': repo, 'status': 1, 'description': err}

        LOGGER.info('Pulling from {0}'.format(repo))
        remote = client.remote(name='origin')
        remote.pull(refspec=cur_branch)

        if changesets is not None and repo in changesets:
            client.git.checkout(changesets[repo]['hash'])

            LOGGER.info('Checked out {0} to {1}'.format(
                repo, changesets[repo]['hash']))

        return {'repo': repo, 'status': 0, 'description': None}
    except Exception as exc:
        LOGGER.exception(
            'Aborting directory {0} '
            'PLEASE FIX. Reason:\n{1}\n'.format(cur_path, exc)
        )

        return {'repo': repo, 'status': 1, 'description': None}
    finally:
        client.close()


def _pull_repo(args):
    repos_path, repo, changesets = args
    if changesets is not None and repo not in changesets:
        LOGGER.debug('Nothing to do for repo {0} because our application does '
                    'not depend on it'.format(repo))
        return {'repo': repo, 'status': 0, 'description': None}

    if repo == 'versions':
        return {'repo': repo, 'status': 0, 'description': None}

    cur_path = '{0}/{1}'.format(repos_path, repo)

    repo_type = None
    try:
        client = git.Repo(cur_path)
        client.close()

        repo_type = 'git'
    except git.exc.InvalidGitRepositoryError:
        try:
            client = hglib.open(cur_path)
            client.close()

            repo_type = 'mercurial'
        except hglib.error.ServerError:
            LOGGER.exception(
                'The repository: {0} is '
                'neither a git or a mercurial repository. Skipping it!'
                '\nReason:\n'.format(cur_path)
            )

            return {
                'repo': repo, 'status': 0,
                'description': 'The repository is neither git or mercurial'
            }

    if repo_type == 'mercurial':
        return _mercurial_pull(cur_path, repo, changesets)
    elif repo_type == 'git':
        return _git_pull(cur_path, repo, changesets)


def _mercurial_clone(repos_path, repo, remote):
    LOGGER.info('Cloning {0}..'.format(repo))

    try:
        hglib.clone(
            '{0}/{1}'.format(remote, repo),
            '{0}/{1}'.format(repos_path, repo)
        )
    except Exception as exc:
        err = 'Failed to clone {0} repository. ' \
              'Description: {1}'.format(repo, exc.args)
        return {'repo': repo, 'status': 1, 'description': err}

    return {'repo': repo, 'status': 0, 'description': None}


def _git_clone(repos_path, repo, remote):
    LOGGER.info('Cloning {0}..'.format(repo))

    try:
        git.Repo().clone_from(
            '{0}/{1}'.format(remote, repo),
            '{0}/{1}'.format(repos_path, repo)
        )
    except Exception as exc:
        err = 'Failed to clone {0} repository. ' \
              'Description: {1}'.format(repo, exc.args)
        return {'repo': repo, 'status': 1, 'description': err}

    return {'repo': repo, 'status': 0, 'description': None}


def _clone_repo(args):
    repos_path, repo, remote, vcs_type = args

    dirs = [name for name in os.listdir(repos_path)
            if os.path.isdir(os.path.join(repos_path, name))]

    if repo in dirs:
        return {'repo': repo, 'status': 0, 'description': None}

    if remote is None:
        return {'repo': repo, 'status': 1,
                'description': 'remote is None. Will not clone'}

    if vcs_type == 'mercurial':
        return _mercurial_clone(repos_path, repo, remote)
    elif vcs_type == 'git':
        return _git_clone(repos_path, repo, remote)


def _goto_version(repos_path, remotes, changesets=None):
    repos_path = os.path.abspath(repos_path)
    args = [[repos_path, name, changesets] for name in os.listdir(repos_path)
             if os.path.isdir(os.path.join(repos_path, name))]

    with Pool(min(len(args), 20)) as p:
        results = p.map(_pull_repo, args)

    err = False
    for res in results:
        if res['status'] == 1:
            err = True
            if res['repo'] is None and res['description'] is None:
                continue

            msg = 'Failed to pull '
            if res['repo'] is not None:
                msg += 'from {0} '.format(res['repo'])
            if res['description'] is not None:
                msg += 'because {0}'.format(res['description'])

            LOGGER.warning(msg)

    if err:
        raise RuntimeError(
            'Failed to pull all the required repos. See log above'
        )

    if changesets is None:
        return

    args = [[repos_path, name, remotes[changesets[name]['vcs_type']],
             changesets[name]['vcs_type']] for name in changesets.keys()]

    with Pool(min(len(args), 10)) as p:
        results = p.map(_clone_repo, args)

    err = False
    for res in results:
        if res['status'] == 1:
            err = True
            if res['repo'] is None and res['description'] is None:
                continue

            msg = 'Failed to clone '
            if res['repo'] is not None:
                msg += 'from {0} '.format(res['repo'])
            if res['description'] is not None:
                msg += 'because {0}'.format(res['description'])

            LOGGER.warning(msg)

    if err:
        raise RuntimeError(
            'Failed to clone all the required repos. See log above'
        )


def main():
    args = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--repos_path',
        required=True,
        help='The path to the repos base dir for changeset generation'
    )
    parser.add_argument(
        '--app_name', default=None, help="The application's name"
    )

    parser.add_argument(
        '--app_version', default=None, help="The application's version"
    )

    parser.add_argument(
        '--git_remote', default=None,
        help="The remote url to pull from git"
    )

    parser.add_argument(
        '--mercurial_remote', default=None,
        help="The remote url to pull from mercurial"
    )

    args = parser.parse_args(args)
    params = copy.deepcopy(vars(args))
    res = goto_version(**params)

    return res


if __name__ == '__main__':
    sys.exit(main())
