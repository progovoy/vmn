#!/usr/bin/env python3
import argparse
import copy
import sys
import os
import logging
import importlib.machinery
import types
import re
from multiprocessing import Pool

sys.path.append('{0}/'.format(os.path.dirname(__file__)))
import stamp_utils

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
            {'git': git_remote, 'mercurial': mercurial_remote},
        )
        return

    versions_path = stamp_utils.get_versions_repo_path(repos_path)
    versions_client, _ = stamp_utils.get_client(versions_path)

    root = versions_client.root()
    tags = versions_client.tags()
    tip_app_tag = None
    tip_app_tag_index = None
    app_tag = None
    app_tag_index = None

    for idx, tag in enumerate(tags):
        if not tag.startswith('{0}_'.format(app_name)):
            continue

        if tip_app_tag is None:
            tip_app_tag = tag
            tip_app_tag_index = idx

        tag_ver = tag.split('{0}_'.format(app_name))[1]
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
    paths = versions_client.status(tag=tip_app_tag)
    for path in paths:
        if not path.endswith('/main_version.py'):
            continue

        # Retrieve the tag of the service
        app_tag = tags[app_tag_index - 1]
        res = re.search('(.+)_(.+)', app_tag)
        app_name = res.groups()[0]
        app_version = res.groups()[1]

        main_ver_path = '{0}/{1}'.format(root, path)

        loader = importlib.machinery.SourceFileLoader(
            'main_version', main_ver_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        services = mod_ver.services
        app_ver_path = '{0}/{1}'.format(root, services[app_name]['path'])

        break

    for path in paths:
        if app_ver_path is None:
            if not path.endswith('/version.py'):
                continue

            app_ver_path = '{0}/{1}'.format(root, path)

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


def _pull_repo(args):
    repos_path, repo, changesets = args
    if changesets is not None and repo not in changesets:
        LOGGER.debug('Nothing to do for repo {0} because our application does '
                     'not depend on it'.format(repo))
        return {'repo': repo, 'status': 0, 'description': None}

    if repo == 'versions':
        return {'repo': repo, 'status': 0, 'description': None}

    cur_path = '{0}/{1}'.format(repos_path, repo)

    client = None
    try:
        client, err = stamp_utils.get_client(cur_path)
        if client is None:
            return {'repo': repo, 'status': 0, 'description': err}
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting pull operation because directory {0} '
            'Reason:\n{1}\n'.format(cur_path, exc)
        )

        return {'repo': repo, 'status': 1, 'description': None}

    try:
        err = client.check_for_pending_changes()
        if err:
            LOGGER.info('{0}. Aborting pull operation '.format(err))
            return {'repo': repo, 'status': 1, 'description': err}

    except Exception as exc:
        LOGGER.exception('Skipping "{0}" directory reason:\n{1}\n'.format(
            cur_path, exc)
        )
        return {'repo': repo, 'status': 0, 'description': None}

    try:
        err = client.check_for_outgoing_changes()
        if err:
            LOGGER.info('{0}. Aborting pull operation'.format(err))
            return {'repo': repo, 'status': 1, 'description': err}

        LOGGER.info('Pulling from {0}'.format(repo))
        # If no changesets were given - update to master
        if changesets is None:
            rev = client.checkout_master()
            client.pull()

            LOGGER.info('Updated {0} to {1}'.format(repo, rev))
        elif repo in changesets:
            client.pull()

            rev = changesets[repo]['hash']
            client.checkout(rev=rev)

            LOGGER.info('Updated {0} to {1}'.format(repo, rev))
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting pull operation because directory {0} '
            'Reason:\n{1}\n'.format(cur_path, exc)
        )

        return {'repo': repo, 'status': 1, 'description': None}

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

    LOGGER.info('Cloning {0}..'.format(repo))
    try:
        if vcs_type == 'mercurial':
            stamp_utils.MercurialBackend.clone(repos_path, repo, remote)
        elif vcs_type == 'git':
            stamp_utils.GitBackend.clone(repos_path, repo, remote)
    except Exception as exc:
        err = 'Failed to clone {0} repository. ' \
              'Description: {1}'.format(repo, exc.args)
        return {'repo': repo, 'status': 1, 'description': err}

    return {'repo': repo, 'status': 0, 'description': None}


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
