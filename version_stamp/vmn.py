#!/usr/bin/env python3
import argparse
from pathlib import Path
import copy
import yaml
import sys
import os
import pathlib
from lockfile import LockFile
from multiprocessing import Pool
import random
import time


CUR_PATH = '{0}/'.format(os.path.dirname(__file__))
sys.path.append(CUR_PATH)
import stamp_utils
from stamp_utils import HostState
from version_stamp import version as __version__

LOGGER = stamp_utils.init_stamp_logger()


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

    return '{0}.{1}.{2}.{3}'.format(major, minor, patch, micro)


class IVersionsStamper(object):
    def __init__(self, conf):
        self._backend = None
        self._name = conf['name']
        self._root_path = conf['root_path']
        self._release_mode = conf['release_mode']
        self._version_template, self._version_template_octats_count = \
            IVersionsStamper.parse_template(conf['version_template'])

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

    def find_matching_version(self, user_repo_details):
        raise NotImplementedError('Please implement this method')

    def stamp_app_version(
            self,
            user_repo_details,
            starting_version,
            override_release_mode=None,
            override_current_version=None,
    ):
        raise NotImplementedError('Please implement this method')

    def stamp_main_system_version(self, override_version=None):
        raise NotImplementedError('Please implement this method')

    def retrieve_remote_changes(self):
        raise NotImplementedError('Please implement this method')

    def publish(self, app_version, main_version=None):
        raise NotImplementedError('Please implement this method')


class VersionControlStamper(IVersionsStamper):
    def __init__(self, conf):
        IVersionsStamper.__init__(self, conf)

        self._app_path = conf['app_path']
        self._app_conf_path = conf['app_conf_path']

        self._app_index_path = conf['app_index_path']
        self._repo_name = '.'

        self._root_app_name = conf['root_app_name']
        self._root_app_path = conf['root_app_path']
        self._extra_info = conf['extra_info']

        self._root_index_path = None
        if self._root_app_path is not None:
            root_ver_path = os.path.dirname(self._root_app_path)
            self._root_index_path = \
                os.path.join(root_ver_path, '_root_index.yml')

    def allocate_backend(self):
        self._backend, _ = stamp_utils.get_client(self._root_path)

    def deallocate_backend(self):
        del self._backend

    def find_matching_version(self, user_repo_details):
        history_revs = self._get_app_changesets()
        if history_revs is None:
            return None

        # Try to find any version of the application matching the
        # user's repositories local state
        for version in history_revs:
            found = True
            for k, v in history_revs[version]['changesets'].items():
                if k not in user_repo_details:
                    found = False
                    break

                # when k is the "main repo" repo
                if self._repo_name == k:
                    user_changeset = self._backend.last_user_changeset()

                    if v['hash'] != user_changeset:
                        found = False
                        break
                elif v['hash'] != user_repo_details[k]['hash']:
                    found = False
                    break

            if found and history_revs[version]['changesets']:
                return version

        return None

    def _write_app_version_file(self, version, changesets, deps, release_mode):
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
        }
        with open(self._app_path, 'w+') as f:
            f.write('# Autogenerated by vmn. Do not edit\n')
            yaml.dump(ver_yml, f, sort_keys=False)

        ver_conf_yml = {
            "conf": {
                "template": self._version_template,
                "deps": deps,
                "extra_info": self._extra_info,
            },
        }

        with open(self._app_conf_path, 'w+') as f:
            msg = '# Autogenerated by vmn. You can edit this ' \
                  'configuration file\n'
            f.write(msg)
            yaml.dump(ver_conf_yml, f, sort_keys=False)

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
            'version': version,
            'services': {},
            "conf": {
                'external_services': {}
            },
        }

        if version != 0:
            ver_yml['services'] = self._get_underlying_services()

        with open(self._root_app_path, 'w+') as f:
            f.write('# Autogenerated by vmn\n')
            yaml.dump(ver_yml, f, sort_keys=False)

    def stamp_app_version(
            self,
            user_repo_details,
            starting_version,
            override_release_mode=None,
            override_current_version=None,
    ):
        if override_release_mode is None:
            override_release_mode = self._release_mode

        # If there is no file - create it
        if not os.path.isfile(self._app_path):
            pathlib.Path(os.path.dirname(self._app_path)).mkdir(
                parents=True, exist_ok=True
            )
            self._write_app_version_file(
                version=starting_version,
                release_mode='init',
                deps={},
                changesets={},
            )

        # If there is no file - create it
        if not os.path.isfile(self._app_index_path):
            hist_yml = {
                starting_version: {
                    'changesets': {}
                },
            }
            with open(self._app_index_path, 'w+') as f:
                f.write('# Autogenerated by vmn\n')
                yaml.dump(hist_yml, f, sort_keys=False)

        flat_dependency_repos = []
        configured_deps = None
        with open(self._app_conf_path) as f:
            data = yaml.safe_load(f)
            configured_deps = data["conf"]["deps"]

            # resolve relative paths
            for rel_path, v in data["conf"]["deps"].items():
                for repo in v:
                    flat_dependency_repos.append(
                        os.path.relpath(
                            os.path.join(
                                self._backend.root(), rel_path, repo
                            ),
                            self._backend.root()
                        ),
                    )

        with open(self._app_path) as f:
            data = yaml.safe_load(f)
            old_version = data["_version"]

        if override_current_version is None:
            override_current_version = old_version

        current_version = gen_app_version(
            override_current_version, override_release_mode
        )

        if self._release_mode == 'debug':
            return current_version

        # User omitted dependencies
        if not configured_deps:
            flat_dependency_repos = ['.']
            configured_deps = {
                os.path.join("../"): {
                    os.path.basename(self._root_path): {
                        'remote': self._backend.remote(),
                        'vcs_type': self._backend.type()
                    }
                }
            }

        if '../' not in configured_deps:
            configured_deps['../'] = {}

        base_name = os.path.basename(self._root_path)
        if base_name not in configured_deps['../']:
            flat_dependency_repos.append('.')
            configured_deps['../'][base_name] = {
                'remote': self._backend.remote(),
                'vcs_type': self._backend.type()
            }

        for repo in flat_dependency_repos:
            if repo in user_repo_details:
                continue

            raise RuntimeError(
                'A dependency repository was specified in '
                'conf.yml file. However repo: {0} does not exist. '
                'Please clone and rerun'.format(
                    os.path.join(self._backend.root(), repo)
                )
            )

        # write version file
        changesets_to_file = {}
        for k in flat_dependency_repos:
            changesets_to_file[k] = user_repo_details[k]

        self._write_app_version_file(
            version=current_version,
            changesets=changesets_to_file,
            deps=configured_deps,
            release_mode=self._release_mode,
        )

        with open(self._app_index_path, 'r+') as f:
            data = yaml.safe_load(f)
            f.seek(0)
            f.write('# Autogenerated by vmn. Do not edit\n')

            data[current_version] = {
                'changesets': changesets_to_file
            }

            yaml.dump(data, f, sort_keys=False)
            f.truncate()

        return current_version

    def stamp_main_system_version(self, override_version=None):
        if self._root_app_name is None:
            return None

        if not os.path.isfile(self._root_app_path):
            self._write_root_version_file(version=0)

        if not os.path.isfile(self._root_index_path):
            with open(self._root_index_path, 'w+') as f:
                f.write('# Autogenerated by vmn. Do not edit\n')
                root_hist_yml = {
                    0: {
                        'services': {},
                        'external_services': {}
                    }
                }
                yaml.dump(root_hist_yml, f, sort_keys=False)

        with open(self._root_app_path) as f:
            data = yaml.safe_load(f)
            old_version = data["version"]

        if override_version is None:
            override_version = old_version

        root_version = int(override_version) + 1

        if self._release_mode == 'debug':
            return root_version

        self._write_root_version_file(version=root_version)

        services = None
        external_services = None
        with open(self._root_app_path) as f:
            data = yaml.safe_load(f)
            services = copy.deepcopy(data['services'])
            external_services = copy.deepcopy(
                data['conf']['external_services']
            )

        with open(self._root_index_path, 'r+') as f:
            data = yaml.safe_load(f)
            f.seek(0)
            f.write('# Autogenerated by vmn. Do not edit\n')

            data[root_version] = {
                'services': services,
                'external_services': external_services
            }

            yaml.dump(data, f, sort_keys=False)
            f.truncate()

        return '{0}'.format(root_version)

    def publish(self, app_version, main_version=None):
        if self._release_mode == 'debug':
            # TODO:: Do we still need it?
            # We may push new files here so give it a try
            try:
                pass
                self._backend.push()
            except Exception as exc:
                LOGGER.error(exc)

            return 0

        version_files = [
            self._app_path,
            self._app_index_path,
            self._app_conf_path
        ]
        if self._root_app_name is not None:
            version_files.append(self._root_app_path)
            version_files.append(self._root_index_path)

        self._backend.commit(
            message='{0}: update to version {1}'.format(
                self._name, app_version),
            user='vmn',
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
                tags.append('{0}_{1}'.format(
                    self._root_app_name, main_version)
                )
            else:
                tags.append(
                    '{0}_{1}'.format('-'.join(s), main_version)
                )

        try:
            self._backend.tag(tags, user='vmn')
        except Exception:
            LOGGER.exception('Logged Exception message:')
            LOGGER.info('Reverting vmn changes for tags: {0} ...'.format(tags))
            self._backend.revert_vmn_changes(tags)

            return 1

        try:
            self._backend.push(tags)
        except Exception:
            LOGGER.exception('Logged Exception message:')
            LOGGER.info('Reverting vmn changes for tags: {0} ...'.format(tags))
            self._backend.revert_vmn_changes(tags)
            # TODO:: git revert this commit when the auto retry
            #  feature will be stable enough
            return 1

        return 0

    def retrieve_remote_changes(self):
        self._backend.pull()

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
            return None

        if os.path.isfile(self._app_index_path):
            with open(self._app_index_path, 'r') as f:
                hist_changesets = yaml.safe_load(f)

        return hist_changesets


def get_version(versions_be_ifc, params):
    user_repo_details = params['user_repos_details']

    ver = versions_be_ifc.find_matching_version(user_repo_details)
    if ver is not None:
        # Good we have found an existing version matching
        # the user_repo_details
        return versions_be_ifc.get_be_formatted_version(ver)

    stamped = False
    retries = 3
    override_release_mode = None
    override_current_version = None
    override_main_current_version = None

    while retries:
        retries -= 1

        # We didn't find any existing version - generate new one
        current_version = versions_be_ifc.stamp_app_version(
            user_repo_details,
            params['starting_version'],
            override_release_mode,
            override_current_version,
        )
        main_ver = versions_be_ifc.stamp_main_system_version(
            override_main_current_version
        )

        err = versions_be_ifc.publish(current_version, main_ver)
        if not err:
            stamped = True
            break

        if err == 1:
            override_current_version = current_version
            override_main_current_version = main_ver
            release_mode = 'micro'

            LOGGER.warning(
                'Failed to publish. Trying to auto-increase '
                'from {0} to {1}'.format(
                    current_version,
                    gen_app_version(current_version, release_mode)
                )
            )

            time.sleep(random.randint(1, 5))

            continue
        else:
            break

    if not stamped:
        raise RuntimeError('Failed to stamp')

    return versions_be_ifc.get_be_formatted_version(current_version)


def init(params):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is already initialized')
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    changeset = be.changeset()

    vmn_path = '{0}/.vmn/'.format(params['root_path'])
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_unique_path = '{0}/{1}'.format(
        vmn_path,
        changeset)
    Path(vmn_unique_path).touch()

    be.commit(
        message=stamp_utils.INIT_COMMIT_MESSAGE,
        user='vmn',
        include=[vmn_path, vmn_unique_path]
    )

    be.push()

    LOGGER.info('Initialized vmn tracking on {0}'.format(params['root_path']))

    return None


def show(params):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.error('vmn tracking is not yet initialized')
        return err

    app_path = params['app_path']
    if not os.path.isfile(app_path):
        LOGGER.error('No ver.yml file under {0}'.format(params['name']))
        return err

    with open(app_path) as f:
        data = yaml.safe_load(f)
        print(data['version'])

    return None


def stamp(params):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is not yet initialized')
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    lock = LockFile(os.path.join(params['root_path'], 'vmn.lock'))
    with lock:
        LOGGER.info('Locked: {0}'.format(lock.path))

        be = VersionControlStamper(params)

        be.allocate_backend()

        try:
            version = get_version(be, params)
        except Exception:
            LOGGER.exception('Logged Exception message:')
            be.deallocate_backend()

            return 1

        LOGGER.info(version)

        be.deallocate_backend()

    LOGGER.info('Released locked: {0}'.format(lock.path))

    return None


def goto_version(params, version):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is not yet initialized')
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    if not os.path.isfile(params['app_path']):
        LOGGER.error('No such app: {0}'.format(params['name']))
        return 1

    if version is None:
        with open(params['app_path'], 'r') as f:
            data = yaml.safe_load(f)
            deps = data["changesets"]
            deps.pop('.')
            if deps:
                for rel_path, v in deps.items():
                    v['hash'] = None

                _goto_version(deps, params['root_path'])
            else:
                be.checkout_branch()

            return 0

    tag_name = params['name'].replace('/', '-')
    tag_name = '{0}_{1}'.format(tag_name, version)
    try:
        be.checkout(tag=tag_name)
    except Exception:
        LOGGER.error(
            'App: {0} with version: {1} was '
            'not found'.format(
                params['name'], version
            )
        )

        return 1

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        deps = data["changesets"]
        deps.pop('.')
        if deps:
            _goto_version(deps, params['root_path'])

    return None


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
        if changeset is None:
            client.pull()
            rev = client.checkout_branch()

            LOGGER.info('Updated {0} to {1}'.format(rel_path, rev))
        else:
            cur_changeset = client.changeset()
            client.pull()
            client.checkout(rev=changeset)

            LOGGER.info('Updated {0} to {1}'.format(rel_path, changeset))
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting pull operation because directory {0} '
            'Reason:\n{1}\n'.format(path, exc)
        )

        try:
            client.checkout(rev=cur_changeset)
        except Exception:
            LOGGER.exception('PLEASE FIX!')

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
        args.append((
            os.path.join(root, rel_path),
            rel_path,
            v['remote'],
            v['vcs_type']
        ))
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

            LOGGER.info(msg)

    args = []
    for rel_path, v in deps.items():
        args.append((
            os.path.join(root, rel_path),
            rel_path,
            v['hash']
        ))

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


def build_world(name, working_dir):
    params = {
        'name': name,
        'working_dir': working_dir,
    }

    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return None

    root_path = os.path.join(be.root())
    params['root_path'] = root_path

    if name is None:
        return params

    app_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        'ver.yml'
    )
    app_conf_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        'conf.yml'
    )
    hist_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        '_index.yml'
    )
    params['app_path'] = app_path
    params['app_conf_path'] = app_conf_path
    app_dir = os.path.dirname(params['app_path'])
    params['app_index_path'] = os.path.join(app_dir, '_index.yml')
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
            '_root_index.yml'
        )

    params['root_app_name'] = root_app_name
    params['root_app_path'] = root_app_path
    params['root_hist_path'] = root_hist_path

    default_repos_path = os.path.join(root_path, '../')
    user_repos_details = HostState.get_user_repo_details(
        {default_repos_path: os.listdir(default_repos_path)},
        root_path
    )
    params['version_template'] = '{0}.{1}.{2}'
    params["extra_info"] = False
    params['user_repos_details'] = user_repos_details

    if not os.path.isfile(app_path):
        return params

    with open(app_conf_path, 'r') as f:
        data = yaml.safe_load(f)
        params['version_template'] = data["conf"]["template"]
        params["extra_info"] = data["conf"]["extra_info"]

        deps = {}
        for rel_path, dep in data["conf"]["deps"].items():
            deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

        user_repos_details.update(
            HostState.get_user_repo_details(deps, root_path)
        )
        params['user_repos_details'] = user_repos_details

    return params


def main(command_line=None):
    parser = argparse.ArgumentParser('vmn')
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=__version__.version
    )

    subprasers = parser.add_subparsers(dest='command')
    subprasers.add_parser(
        'init',
        help='initialize version tracking'
    )
    pshow = subprasers.add_parser(
        'show',
        help='show app version'
    )
    pshow.add_argument(
        'name', help="The application's name"
    )
    pstamp = subprasers.add_parser('stamp', help='stamp version')
    pstamp.add_argument(
        '-r', '--release-mode',
        choices=['major', 'minor', 'patch', 'micro'],
        default='debug',
        required=True,
        help='major / minor / patch / micro'
    )

    pstamp.add_argument(
        '-s', '--starting-version',
        default='0.0.0.0',
        required=False,
        help='Starting version'
    )

    pstamp.add_argument(
        'name', help="The application's name"
    )

    pgoto = subprasers.add_parser('goto', help='go to version')
    pgoto.add_argument(
        '-v', '--version',
        default=None,
        required=False,
        help="The version to go to"
    )
    pgoto.add_argument(
        'name',
        help="The application's name"
    )

    cwd = os.getcwd()
    if 'VMN_WORKING_DIR' in os.environ:
        cwd = os.environ['VMN_WORKING_DIR']

    args = parser.parse_args(command_line)
    if 'name' in args:
        params = build_world(args.name, cwd)
    else:
        params = build_world(None, cwd)

    err = 0
    if args.command == 'init':
        err = init(params)
    if args.command == 'show':
        err = show(params)
    elif args.command == 'stamp':
        params['release_mode'] = args.release_mode
        params['starting_version'] = args.starting_version
        err = stamp(params)
    elif args.command == 'goto':
        err = goto_version(params, args.version)

    return err


if __name__ == '__main__':
    err = main()
    if err:
        sys.exit(1)

    sys.exit(0)
