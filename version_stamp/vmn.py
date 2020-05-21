#!/usr/bin/env python3
import argparse
from pathlib import Path
import copy
import yaml
import json
import sys
import os
import pathlib
import importlib.machinery
import types
from lockfile import LockFile
import time
from multiprocessing import Pool

CUR_PATH = '{0}/'.format(os.path.dirname(__file__))
sys.path.append(CUR_PATH)
import stamp_utils
from stamp_utils import HostState

LOGGER = stamp_utils.init_stamp_logger()
CWD = os.getcwd()


def gen_main_version(main_ver_mod, release_mode):
    if release_mode != 'debug':
        main_ver = str(int(main_ver_mod.build_num) + 1)
    else:
        main_ver = str(int(main_ver_mod.build_num))

    main_date_ver = main_ver_mod.version

    strings = time.strftime("%y,%m")
    strings = strings.split(',')
    tmp_date_ver = '{0}.{1}'.format(strings[0], strings[1])
    if not main_date_ver.startswith(tmp_date_ver):
        main_ver = '1'
    formatted_main_ver = '{0}.{1}'.format(tmp_date_ver, main_ver)
    return formatted_main_ver, main_ver


def gen_app_version(current_version, release_mode):
    try:
        major, minor, patch, micro = current_version.split('.')
    except ValueError:
        major, minor, patch = current_version.split('.')
        micro = str(0)

    if release_mode == 'major':
        major = str(int(major) + 1)
        minor = str(0)
        patch = str(0)
        micro = str(0)
    elif release_mode == 'minor':
        minor = str(int(minor) + 1)
        patch = str(0)
        micro = str(0)
    elif release_mode == 'patch':
        patch = str(int(patch) + 1)
        micro = str(0)
    elif release_mode == 'micro':
        micro = str(int(micro) + 1)

    current_version = '{0}.{1}.{2}.{3}'.format(major, minor, patch, micro)

    return current_version


class IVersionsStamper(object):
    def __init__(self, conf):
        self._backend = None
        self._name = conf['name']
        self._root_path = conf['root_path']
        self._release_mode = conf['release_mode']
        self._version_template, self._version_template_octats_count = \
            IVersionsStamper.parse_template(conf['version_template'])

        self._root_version_template, self._root_version_template_octats_count = \
            None, None
        if conf['root_version_template'] is not None:
            self._root_version_template, self._root_version_template_octats_count = \
                IVersionsStamper.parse_template(conf['root_version_template'])

    @staticmethod
    def parse_template(template):
        placeholders = (
            '{0}', '{1}', '{2}', '{3}', '{NON_EXISTING_PLACEHOLDER}'
        )
        templates = [None, None, None, None]

        if len(template) > 30:
            raise RuntimeError('Template too long: max 30 chars')

        pos = template.find(placeholders[0])
        if pos < 0:
            raise RuntimeError('Invalid template must include {0} at least')

        prefix = template[:pos]
        for placeholder in placeholders:
            prefix = prefix.replace(placeholder, '')

        for i in range(len(placeholders) - 1):
            cur_pos = template.find(placeholders[i])
            next_pos = template.find(placeholders[i + 1])
            if next_pos < 0:
                next_pos = None

            tmp = template[cur_pos:next_pos]
            for placeholder in placeholders:
                tmp = tmp.replace(placeholder, '')

            tmp = '{0}{1}'.format(placeholders[i], tmp)

            templates[i] = tmp

            if next_pos is None:
                break

        ver_format = ''
        octats_count = 0
        templates[0] = '{0}{1}'.format(prefix, templates[0])
        for template in templates:
            if template is None:
                break

            ver_format += template
            octats_count += 1

        return ver_format, octats_count

    @staticmethod
    def get_formatted_version(version, version_template, octats_count):
        octats = version.split('.')
        if len(octats) > 4:
            raise RuntimeError('Version is too long. Maximum is 4 octats')

        for i in range(4 - len(octats)):
            octats.append('0')

        return version_template.format(
            *(octats[:octats_count])
        )

    def get_be_formatted_version(self, version):
        return IVersionsStamper.get_formatted_version(
            version,
            self._version_template,
            self._version_template_octats_count
        )

    def allocate_backend(self):
        raise NotImplementedError('Please implement this method')

    def deallocate_backend(self):
        raise NotImplementedError('Please implement this method')

    def find_version(self, current_changesets):
        raise NotImplementedError('Please implement this method')

    def stamp_app_version(self, current_changesets):
        raise NotImplementedError('Please implement this method')

    def stamp_main_system_version(self, service_version):
        raise NotImplementedError('Please implement this method')

    def publish(self, app_version, main_version=None):
        raise NotImplementedError('Please implement this method')


class VersionControlStamper(IVersionsStamper):
    def __init__(self, conf):
        IVersionsStamper.__init__(self, conf)

        self._app_path = conf['app_path']

        app_dir = os.path.dirname(self._app_path)
        self._app_index_path = \
            os.path.join(app_dir, '_index.yml')
        self._repo_name = '.'

        self._root_app_name = conf['root_app_name']
        self._root_app_path = conf['root_app_path']
        self._extra_info = conf['extra_info']

        self._root_index_path = None
        if self._root_app_path is not None:
            root_ver_path = os.path.dirname(self._root_app_path)
            self._root_index_path = \
                os.path.join(root_ver_path, '_root_history.yml')

    def allocate_backend(self):
        self._backend, _ = stamp_utils.get_client(self._root_path)

    def deallocate_backend(self):
        del self._backend

    def find_version(self, changesets_dict):
        version, latest_revs, history_revs = self._get_app_changesets()
        if version is None:
            return None

        # Try to find any version of the application matching the
        # repositories local state
        found = True
        for k, v in latest_revs.items():
            if k not in changesets_dict:
                found = False
                break
            if self._repo_name == k:
                parents = self._backend.parents()
                if len(parents) > 1:
                    if changesets_dict[k]['hash'] in parents:
                        raise RuntimeError(
                            'Somehow vmn has stamped on a '
                            'merge commit.FIX!'
                        )

                if v['hash'] != parents[0]:
                    found = False
                    break
            elif v['hash'] != changesets_dict[k]['hash']:
                found = False
                break

        if found and latest_revs:
            return version

        # If in repo and not on latest tag - version not found.
        # This is because there is no way of finding
        # current changeset in self._repo_name's versions history
        if self._repo_name in latest_revs:
            return None

        # If the history is empty - version not found
        if not history_revs:
            return None

        for tag in history_revs:
            found = True
            for k, v in history_revs[tag].items():
                if k not in changesets_dict:
                    found = False
                    break
                if v['hash'] != changesets_dict[k]['hash']:
                    found = False
                    break

            if found and history_revs[tag]:
                return tag

        return None

    def _write_app_version_file(self, version, changesets, release_mode):
        info = {}
        if self._extra_info:
            info['env'] = dict(os.environ)

        ver_yml = {
            'name': self._name,
            'version': IVersionsStamper.get_formatted_version(
                version,
                self._version_template,
                self._version_template_octats_count),
            '_version': version,
            "release_mode": release_mode,
            "changesets": changesets,
            "info": info,
            "conf": {
                "template": self._version_template,
                "deps": {
                    os.path.join("../"): {
                        os.path.basename(self._root_path): {
                            'remote': self._backend.remote(),
                            'vcs_type': self._backend.type()
                        }
                    }
                },
                "extra_info": self._extra_info,
            },
        }
        with open(self._app_path, 'w+') as f:
            f.write('# Autogenerated by vmn\n')
            yaml.dump(ver_yml, f, sort_keys=False)

    def _get_underlying_services(self):
        path = os.path.join(
            self._backend.root(),
            '.vmn',
            self._root_app_name,
        )

        underlying_apps = {}
        if os.path.isfile(self._root_app_path):
            with open(self._root_app_path, 'r') as f:
                data = yaml.safe_load(f)
                underlying_apps = data['services']

        for item in os.listdir(path):
            cur_path = os.path.join(path, item, 'ver.yml')
            if os.path.isfile(cur_path):
                with open(cur_path) as f:
                    data = yaml.safe_load(f)
                    if data['name'] not in underlying_apps:
                        LOGGER.info(
                            'Adding {0} with version {1} as an underlying '
                            ' service for {2}'.format(
                                self._name,
                                data['_version'],
                                self._root_app_name
                            )
                        )

                    underlying_apps[data['name']] = data['_version']

        return underlying_apps

    def _write_root_version_file(self, version):
        ver_yml = {
            'name': self._root_app_name,
            'version': IVersionsStamper.get_formatted_version(
                version,
                self._root_version_template,
                self._root_version_template_octats_count),
            '_version': version,
            'services': {},
            'release_mode': None,
            "conf": {
                "template": self._root_version_template,
                'external_services': {}
            },
        }

        if version != '0.0.0.0':
            ver_yml['services'] = self._get_underlying_services()
            ver_yml['release_mode'] = self._release_mode

        with open(self._root_app_path, 'w+') as f:
            f.write('# Autogenerated by vmn\n')
            yaml.dump(ver_yml, f, sort_keys=False)

    def stamp_app_version(self, current_changesets):
        # If there is no file - create it
        if not os.path.isfile(self._app_path):
            pathlib.Path(os.path.dirname(self._app_path)).mkdir(
                parents=True, exist_ok=True
            )
            self._write_app_version_file(
                version="0.0.0.0",
                release_mode='init',
                changesets={},
            )

        # If there is no file - create it
        if not os.path.isfile(self._app_index_path):
            hist_yml = {
                "0.0.0.0": {
                    'changesets': {}
                },
            }
            with open(self._app_index_path, 'w+') as f:
                f.write('# Autogenerated by vmn\n')
                yaml.dump(hist_yml, f, sort_keys=False)

        with open(self._app_path) as f:
            data = yaml.safe_load(f)
            custom_repos = []
            for rel_path, v in data["conf"]["deps"].items():
                for repo in v:
                    custom_repos.append(
                        os.path.relpath(
                            os.path.join(rel_path, repo),
                            self._backend.root()
                        ),
                    )

            old_version = data["_version"]
            old_changesets = copy.deepcopy(data["changesets"])

        current_version = gen_app_version(
            old_version, self._release_mode
        )

        if self._release_mode == 'debug':
            return current_version

        if custom_repos is not None:
            for repo in custom_repos:
                if repo in current_changesets:
                    continue

                raise RuntimeError(
                    'Dependency repositories were specified in '
                    'ver.yml file. However repo: {0} does not exist '
                    'in your repos_path. Please fix and rerun'.format(repo)
                )

        # write version file
        changesets_to_file = current_changesets
        if custom_repos:
            changesets_to_file = {}
            for k in custom_repos:
                changesets_to_file[k] = current_changesets[k]

        self._write_app_version_file(
            version=current_version,
            changesets=changesets_to_file,
            release_mode=self._release_mode,
        )

        with open(self._app_index_path, 'r+') as f:
            data = yaml.safe_load(f)
            f.seek(0)
            f.write('# Autogenerated by vmn. Do not edit\n')
            data[old_version] = {
                'changesets': old_changesets
            }
            yaml.dump(data, f, sort_keys=False)
            f.truncate()

        return current_version

    def stamp_main_system_version(self, service_version):
        if self._root_app_name is None:
            return None

        if not os.path.isfile(self._root_app_path):
            self._write_root_version_file(version='0.0.0.0')

        if not os.path.isfile(self._root_index_path):
            with open(self._root_index_path, 'w+') as f:
                f.write('# Autogenerated by vmn. Do not edit\n')
                root_hist_yml = {
                    '0.0.0.0': {
                        'services': {},
                        'external_services': {}
                    }
                }
                yaml.dump(root_hist_yml, f, sort_keys=False)

        with open(self._root_app_path) as f:
            data = yaml.safe_load(f)
            old_services = copy.deepcopy(data['services'])
            old_version = data["_version"]
            old_external_services = copy.deepcopy(
                data['conf']['external_services']
            )

        root_version = gen_app_version(
            old_version, self._release_mode
        )

        if self._release_mode == 'debug':
            return root_version

        self._write_root_version_file(version=root_version)

        with open(self._root_index_path, 'r+') as f:
            data = yaml.safe_load(f)
            f.seek(0)
            f.write('# Autogenerated by vmn. Do not edit\n')
            data[old_version] = {
                'services': old_services,
                'external_services': old_external_services
            }

            yaml.dump(data, f, sort_keys=False)
            f.truncate()

        return '{0}'.format(root_version)

    def publish(self, app_version, main_version=None):
        if self._release_mode == 'debug':
            # We may push new files here so give it a try
            try:
                pass
                self._backend.push()
            except Exception as exc:
                LOGGER.error(exc)

            return

        version_files = [
            self._app_path,
            self._app_index_path
        ]
        if self._root_app_name is not None:
            version_files.append(self._root_app_path)
            version_files.append(self._root_index_path)

        self._backend.commit(
            message='{0}: update to version {1}'.format(
                self._name, app_version),
            user='version_manager',
            include=version_files
        )

        s = os.path.split(self._name)
        if not s[0]:
            tags = ['{0}_{1}'.format(s[1], app_version)]
        else:
            tags = ['{0}_{1}'.format('-'.join(s), app_version)]
        if main_version is not None:
            s = os.path.split(self._root_app_name)
            if not s[0]:
                tags.append('{0}_{1}'.format(self._root_app_name, main_version))
            else:
                tags.append(
                    '{0}_{1}'.format('-'.join(s), main_version)
                )

        try:
            self._backend.tag(tags, user='version_manager')
        except Exception as exc:
            LOGGER.exception('Failed to tag')
            raise RuntimeError()

        self._backend.push()

    def _delete_dangling_tags(self):
        tags = self._backend.tags()

        tags_to_delete = []
        for tag in tags:
            # Find the last occurrence of _ on the tag and extract an
            # app name from it
            tmp = tag[:tag.rfind('_')]
            if not tmp == '-'.join(os.path.split(self._name)):
                continue

            tags_to_delete.append(tag)

    def _get_app_changesets(self):
        hist_changesets = {}
        if not os.path.isfile(self._app_path):
            return None, None, None

        with open(self._app_path, 'r') as f:
            data = yaml.safe_load(f)
            current_changesets = data['changesets']
            version = data['_version']

        if os.path.isfile(self._app_index_path):
            with open(self._app_index_path, 'r') as f:
                hist_changesets = yaml.safe_load(f)

        return version, current_changesets, hist_changesets


def get_version(versions_be_ifc, params):
    current_changesets = params['changesets']
    ver = versions_be_ifc.find_version(current_changesets)
    if ver is not None:
        # Good we have found an existing version matching
        # the current_changesets
        return versions_be_ifc.get_be_formatted_version(ver)

    # We didn't find any existing version - generate new one
    current_version = versions_be_ifc.stamp_app_version(
        current_changesets
    )
    formatted_main_ver = versions_be_ifc.stamp_main_system_version(
        current_version
    )
    versions_be_ifc.publish(current_version, formatted_main_ver)

    return versions_be_ifc.get_be_formatted_version(current_version)


def init():
    be, err = stamp_utils.get_client(CWD)
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return

    if os.path.isdir('{0}/.vmn'.format(be.root())):
        LOGGER.info('vmn tracking is already initialized')
        return

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    changeset = be.changeset()

    vmn_path = '{0}/.vmn/'.format(be.root())
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_unique_path = '{0}/{1}'.format(
        vmn_path,
        changeset)
    Path(vmn_unique_path).touch()

    be.commit(
        message='Initialized vmn tracking',
        user='vmn',
        include=[vmn_path, vmn_unique_path]
    )

    be.push()


def show(name):
    be, err = stamp_utils.get_client(CWD)
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return

    if not os.path.isdir('{0}/.vmn'.format(be.root())):
        LOGGER.error('vmn tracking is not yet initialized')
        return

    root_path = os.path.join(be.root())
    app_path = os.path.join(
        root_path,
        '.vmn',
        name,
        'ver.yml'
    )
    if not os.path.isfile(app_path):
        LOGGER.error('No ver.yml file under {0}'.format(name))
        return

    with open(app_path) as f:
        data = yaml.safe_load(f)
        print(data['version'])


def stamp(params):
    be, err = stamp_utils.get_client(CWD)
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return

    if not os.path.isdir('{0}/.vmn'.format(be.root())):
        LOGGER.info('vmn tracking is not yet initialized')
        return

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    lock = LockFile(os.path.join(params['root_path'], 'vmn.lock'))
    with lock:
        LOGGER.info('Locked: {0}'.format(lock.path))

        be = VersionControlStamper(params)

        be.allocate_backend()

        version = get_version(be, params)
        LOGGER.info(version)

        be.deallocate_backend()

    LOGGER.info('Released locked: {0}'.format(lock.path))

    return 0


def goto_version(params, version):
    be, err = stamp_utils.get_client(CWD)
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return

    if not os.path.isdir('{0}/.vmn'.format(be.root())):
        LOGGER.info('vmn tracking is not yet initialized')
        return

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return

    with open(params['app_path']) as f:
        data = yaml.safe_load(f)
        deps = data["changesets"]

    if version is None:
        _goto_version(deps, params['root_path'])

        return 0

        if tip_app_tag_index == app_tag_index:
            _goto_version(
                repos_path,
                {'git': git_remote, 'mercurial': mercurial_remote},
                current_changesets,
            )
            return 0

        app_hist_ver_path = '{0}/{1}'.format(
            app_ver_dir_path, '_index.yml')

        if not os.path.isfile(app_hist_ver_path):
            LOGGER.error(
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
    path, rel_path, changeset = args

    client = None
    try:
        client, err = stamp_utils.get_client(path)
        if client is None:
            return {'repo': rel_path, 'status': 0, 'description': err}
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting pull operation because directory {0} '
            'Reason:\n{1}\n'.format(path, exc)
        )

        return {'repo': rel_path, 'status': 1, 'description': None}

    try:
        err = client.check_for_pending_changes()
        if err:
            LOGGER.info('{0}. Aborting pull operation '.format(err))
            return {'repo': rel_path, 'status': 1, 'description': err}

    except Exception as exc:
        LOGGER.exception('Skipping "{0}" directory reason:\n{1}\n'.format(
            path, exc)
        )
        return {'repo': rel_path, 'status': 0, 'description': None}

    try:
        err = client.check_for_outgoing_changes()
        if err:
            LOGGER.info('{0}. Aborting pull operation'.format(err))
            return {'repo': rel_path, 'status': 1, 'description': err}

        LOGGER.info('Pulling from {0}'.format(rel_path))

        client.pull()
        client.checkout(rev=changeset)

        LOGGER.info('Updated {0} to {1}'.format(rel_path, changeset))
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting pull operation because directory {0} '
            'Reason:\n{1}\n'.format(path, exc)
        )

        return {'repo': rel_path, 'status': 1, 'description': None}

    return {'repo': rel_path, 'status': 0, 'description': None}


def _clone_repo(args):
    path, rel_path, remote, vcs_type = args

    LOGGER.info('Cloning {0}..'.format(rel_path))
    try:
        if vcs_type == 'mercurial':
            stamp_utils.MercurialBackend.clone(path, remote)
        elif vcs_type == 'git':
            stamp_utils.GitBackend.clone(path, remote)
    except Exception as exc:
        err = 'Failed to clone {0} repository. ' \
              'Description: {1}'.format(rel_path, exc.args)
        return {'repo': rel_path, 'status': 1, 'description': err}

    return {'repo': rel_path, 'status': 0, 'description': None}


def _goto_version(deps, root):
    args = []
    for rel_path, v in deps.items():
        args.append((os.path.join(root, rel_path), rel_path, v['remote'],
                     v['vcs_type']))
    with Pool(min(len(args), 10)) as p:
        results = p.map(_clone_repo, args)

    for res in results:
        if res['status'] == 1:
            if res['repo'] is None and res['description'] is None:
                continue

            msg = 'Failed to clone '
            if res['repo'] is not None:
                msg += 'from {0} '.format(res['repo'])
            if res['description'] is not None:
                msg += 'because {0}'.format(res['description'])

            LOGGER.debug(msg)

    args = []
    for rel_path, v in deps.items():
        args.append((os.path.join(root, rel_path), rel_path, v['hash']))

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


def _build_world(params):
    if 'name' not in params:
        return

    params['name'] = os.path.split(params['name'])
    params['name'] = os.path.join(*params['name'])

    be, err = stamp_utils.get_client(CWD)
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return

    root_path = os.path.join(be.root())
    app_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        'ver.yml'
    )
    hist_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        '_index.yml'
    )
    params['root_path'] = root_path
    params['app_path'] = app_path
    params['hist_path'] = hist_path
    params['repo_name'] = os.path.basename(root_path)

    root_app_name = params['name'].split('/')
    if len(root_app_name) == 1:
        root_app_name = None
    else:
        root_app_name = '/'.join(root_app_name[:-1])

    root_app_path = None
    root_hist_path = None
    if root_app_name is not None:
        root_app_path = os.path.join(
            root_path,
            '.vmn',
            root_app_name,
            'root_ver.yml'
        )
        root_hist_path = os.path.join(
            root_path,
            '.vmn',
            root_app_name,
            '_root_history.yml'
        )

    params['root_app_name'] = root_app_name
    params['root_app_path'] = root_app_path
    params['root_hist_path'] = root_hist_path

    default_repos_path = os.path.join(root_path, '../')
    changesets = HostState.get_current_changeset(
        {default_repos_path: os.listdir(default_repos_path)},
        root_path
    )
    params['version_template'] = '{0}.{1}.{2}'
    params['root_version_template'] = '{0}.{1}.{2}'
    params["extra_info"] = False
    params['changesets'] = changesets

    if not os.path.isfile(app_path):
        return

    with open(app_path, 'r') as f:
        data = yaml.safe_load(f)
        params['version_template'] = data["conf"]["template"]
        params["extra_info"] = data["conf"]["extra_info"]

        params['root_version_template'] = None
        if root_app_path is not None and os.path.isfile(
                root_app_path):
            with open(root_app_path) as root_f:
                root_data = yaml.safe_load(root_f)
                params['root_version_template'] = root_data["conf"][
                    "template"]

        deps = {}
        for rel_path, dep in data["conf"]["deps"].items():
            deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

        changesets = HostState.get_current_changeset(deps, root_path)
        params['changesets'] = changesets


def main(command_line=None):
    parser = argparse.ArgumentParser('vmn')

    subprasers = parser.add_subparsers(dest='command')
    subprasers.add_parser(
        'init',
        help='initialize version tracking'
    )
    pshow = subprasers.add_parser(
        'show',
        help='initialize version tracking'
    )
    pshow.add_argument(
        'name', help="The application's name"
    )
    pstamp = subprasers.add_parser('stamp', help='stamp version')
    pstamp.add_argument(
        '-r', '--release-mode',
        choices=['major', 'minor', 'patch', 'micro', 'debug'],
        default='debug',
        required=True,
        help='major / minor / patch / micro / debug'
    )

    pstamp.add_argument(
        'name', help="The application's name"
    )

    pgoto = subprasers.add_parser('goto', help='go to version')
    pgoto.add_argument(
        'name',
        help="The application's name"
    )
    pgoto.add_argument(
        '-v', '--version',
        default=None,
        required=False,
        help="The version to go to"
    )

    args = parser.parse_args(command_line)
    params = copy.deepcopy(vars(args))
    _build_world(params)

    if args.command == 'init':
        init()
    if args.command == 'show':
        show(args.name)
    elif args.command == 'stamp':
        stamp(params)
    elif args.command == 'goto':
        goto_version(params, args.version)


if __name__ == '__main__':
    main()
