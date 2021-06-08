#!/usr/bin/env python3
import argparse
from pathlib import Path
import copy
import yaml
import sys
import os
import pathlib
from filelock import FileLock
from multiprocessing import Pool
import random
import time
import re


CUR_PATH = '{0}/'.format(os.path.dirname(__file__))
VER_FILE_NAME = 'last_known_app_version.yml'
sys.path.append(CUR_PATH)
import stamp_utils
from stamp_utils import HostState
import version as version_mod

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
        self._name = conf['name']
        self._root_path = conf['root_path']
        self._backend, _ = stamp_utils.get_client(self._root_path)
        self._release_mode = conf['release_mode']
        self._app_dir_path = conf['app_dir_path']
        self._app_conf_path = conf['app_conf_path']
        self._starting_version = conf['starting_version']
        self._repo_name = '.'

        self._root_app_name = conf['root_app_name']
        self._root_app_conf_path = conf['root_app_conf_path']
        self._root_app_dir_path = conf['root_app_dir_path']
        self._extra_info = conf['extra_info']
        self._version_file_path = '{}/{}'.format(
            self._app_dir_path, VER_FILE_NAME)

        self._version_template, self._version_template_octats_count = \
            IVersionsStamper.parse_template(conf['version_template'])

        self._raw_configured_deps = conf['raw_configured_deps']
        self.actual_deps_state = conf["actual_deps_state"]
        self._flat_configured_deps = self.get_deps_changesets()

        ver_info_form_repo = \
            self._backend.get_vmn_version_info(
                app_name=self._name
            )
        self.tracked = ver_info_form_repo is not None

        self._version_info_message = {
            'vmn_info': {
                'description_message_version': '1',
                'vmn_version': version_mod.version
            },
            'stamping': {
                'msg': '',
                'app': {
                    'name': self._name,
                    'changesets': self.actual_deps_state,
                    'version': IVersionsStamper.get_formatted_version(
                        '0.0.0.0',
                        self._version_template,
                        self._version_template_octats_count
                    ),
                    '_version': '0.0.0.0',
                    "release_mode": self._release_mode,
                    "previous_version": '0.0.0.0',
                    "stamped_on_branch": self._backend.get_active_branch(),
                    "info": {},
                },
                'root_app': {}
            }
        }

        if self._root_app_name is not None:
            self._version_info_message['stamping']['root_app'] = {
                'name': self._root_app_name,
                'version': 0,
                'latest_service': self._name,
                'services': {self._name: '0.0.0.0'},
                'external_services': {},
            }

    def __del__(self):
        del self._backend

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

    @staticmethod
    def write_version_to_file(file_path: str, version_number: str) -> None:
        # this method will write the stamped ver of an app to a file,
        # weather the file pre exists or not
        try:
            with open(file_path, 'w') as fid:
                ver_dict = {'last_stamped_version': version_number}
                yaml.dump(ver_dict, fid)
        except IOError as e:
            LOGGER.exception('there was an issue writing ver file: {}'
                             '\n{}'.format(file_path, e))
            raise IOError(e)
        except Exception as e:
            LOGGER.exception(e)
            raise RuntimeError(e)

    def get_deps_changesets(self):
        flat_dependency_repos = []

        # resolve relative paths
        for rel_path, v in self._raw_configured_deps.items():
            for repo in v:
                flat_dependency_repos.append(
                    os.path.relpath(
                        os.path.join(
                            self._backend.root(), rel_path, repo
                        ),
                        self._backend.root()
                    ),
                )

        return flat_dependency_repos

    def get_be_formatted_version(self, version):
        return IVersionsStamper.get_formatted_version(
            version,
            self._version_template,
            self._version_template_octats_count
        )

    def find_matching_version(self):
        raise NotImplementedError('Please implement this method')

    def create_config_files(self):
        # If there is no file - create it
        if not os.path.isfile(self._app_conf_path):
            pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
                parents=True, exist_ok=True
            )

            ver_conf_yml = {
                "conf": {
                    "template": self._version_template,
                    "deps": self._raw_configured_deps,
                    "extra_info": self._extra_info,
                },
            }

            with open(self._app_conf_path, 'w+') as f:
                msg = '# Autogenerated by vmn. You can edit this ' \
                      'configuration file\n'
                f.write(msg)
                yaml.dump(ver_conf_yml, f, sort_keys=True)

        if self._root_app_name is None:
            return

        if os.path.isfile(self._root_app_conf_path):
            return

        pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
            parents=True, exist_ok=True
        )

        ver_yml = {
            "conf": {
                'external_services': {}
            },
        }

        with open(self._root_app_conf_path, 'w+') as f:
            f.write('# Autogenerated by vmn\n')
            yaml.dump(ver_yml, f, sort_keys=True)

    def stamp_app_version(
            self,
            override_release_mode=None,
            override_current_version=None,
    ):
        raise NotImplementedError('Please implement this method')

    def stamp_main_system_version(self, override_version=None):
        raise NotImplementedError('Please implement this method')

    def retrieve_remote_changes(self):
        raise NotImplementedError('Please implement this method')

    def publish(self, app_version, main_version):
        raise NotImplementedError('Please implement this method')


class VersionControlStamper(IVersionsStamper):
    def __init__(self, conf):
        IVersionsStamper.__init__(self, conf)

    def find_matching_version(self):
        app_tag_name = \
            stamp_utils.VersionControlBackend.get_tag_name(
                self._name,
                version=None
            )

        # Try to find any version of the application matching the
        # user's repositories local state
        for tag in self._backend.tags():
            if not re.match(
                r'{}_\d+\.\d+\.\d+\.\d+$'.format(app_tag_name),
                tag
            ):
                continue

            ver_info = self._backend.get_vmn_version_info(tag_name=tag)
            if ver_info is None:
                continue

            found = True
            for k, v in ver_info['stamping']['app']['changesets'].items():
                if k not in self.actual_deps_state:
                    found = False
                    break

                # when k is the "main repo" repo
                if self._repo_name == k:
                    user_changeset = \
                        self._backend.last_user_changeset()

                    if v['hash'] != user_changeset:
                        found = False
                        break
                elif v['hash'] != self.actual_deps_state[k]['hash']:
                    found = False
                    break

            if found:
                return ver_info['stamping']['app']['_version']

        return None

    def get_version_number_from_file(self) -> str or None:
        try:
            with open(self._version_file_path, 'r') as fid:
                ver_dict = yaml.safe_load(fid)
            return ver_dict.get('last_stamped_version')
        except FileNotFoundError as e:
            LOGGER.debug('could not find version file: {}'.format(
                self._version_file_path)
            )
            LOGGER.debug('{}'.format(e))
            return None

    def decide_app_version_by_source(self) -> str:
        ver_info_form_repo = \
            self._backend.get_vmn_version_info(app_name=self._name)
        tracked = ver_info_form_repo is not None
        only_initialized = tracked and \
            ver_info_form_repo['stamping']['app']['_version'] == '0.0.0.0'

        if only_initialized or not tracked:
            # first stamp
            return self._starting_version

        version = ver_info_form_repo['stamping']['app']["_version"]
        version_str_from_file = self.get_version_number_from_file()
        if version_str_from_file:
            version = version_str_from_file

        return version

    def stamp_app_version(
            self,
            override_release_mode=None,
            override_current_version=None,
    ):
        if override_release_mode is None:
            override_release_mode = self._release_mode

        old_version = self.decide_app_version_by_source()

        if override_current_version is None:
            override_current_version = old_version

        # TODO:: optimization find max here

        current_version = gen_app_version(
            override_current_version, override_release_mode
        )

        VersionControlStamper.write_version_to_file(
            file_path=self._version_file_path,
            version_number=current_version
        )

        for repo in self._flat_configured_deps:
            if repo in self.actual_deps_state:
                continue

            raise RuntimeError(
                'A dependency repository was specified in '
                'conf.yml file. However repo: {0} does not exist. '
                'Please clone and rerun'.format(
                    os.path.join(self._backend.root(), repo)
                )
            )

        info = {}
        if self._extra_info:
            info['env'] = dict(os.environ)

        self._version_info_message['stamping']['app']['version'] = \
            IVersionsStamper.get_formatted_version(
                current_version,
                self._version_template,
                self._version_template_octats_count
        )
        self._version_info_message['stamping']['app']['_version'] = \
            current_version
        self._version_info_message['stamping']['app']['previous_version'] = \
            old_version
        self._version_info_message['stamping']['app']['info'] = \
            info

        return current_version

    def stamp_main_system_version(
            self,
            override_version=None,
    ):
        if self._root_app_name is None:
            return None

        ver_info = self._backend.get_vmn_version_info(
            root_app_name=self._root_app_name
        )
        if ver_info is None:
            old_version = 0
        else:
            old_version = ver_info['stamping']['root_app']["version"]

        if override_version is None:
            override_version = old_version
        root_version = int(override_version) + 1

        with open(self._root_app_conf_path) as f:
            data = yaml.safe_load(f)
            external_services = copy.deepcopy(
                data['conf']['external_services']
            )

        if ver_info is None:
            services = {}
        else:
            root_app = ver_info['stamping']['root_app']
            services = copy.deepcopy(root_app['services'])

        self._version_info_message['stamping']['root_app'] = {
            'version': root_version,
            'services': services,
            'external_services': external_services,
        }

        msg_root_app = self._version_info_message['stamping']['root_app']
        msg_app = self._version_info_message['stamping']['app']
        msg_root_app['services'][self._name] = msg_app['_version']

        return '{0}'.format(root_version)

    def publish(self, app_version, main_version):
        version_files = [self._app_conf_path]
        if app_version != '0.0.0.0':
            version_files.append(self._version_file_path)
        if self._root_app_name is not None:
            version_files.append(self._root_app_conf_path)

        self._version_info_message['stamping']['msg'] = \
            '{0}: update to version {1}'.format(
                self._name, app_version
            )
        msg = '{0}: Stamping version {1}\n\n'.format(self._name, app_version) + \
            yaml.dump(self._version_info_message, sort_keys=True)
        self._backend.commit(
            message=msg,
            user='vmn',
            include=version_files
        )

        tags = [stamp_utils.VersionControlBackend.get_tag_name(
            self._name, app_version)
        ]

        if main_version is not None:
            tags.append(
                stamp_utils.VersionControlBackend.get_tag_name(
                    self._root_app_name, main_version)
            )

        all_tags = []
        all_tags.extend(tags)

        try:
            self._backend.tag(tags, user='vmn')
        except Exception:
            LOGGER.exception('Logged Exception message:')
            LOGGER.info('Reverting vmn changes for tags: {0} ...'.format(tags))
            self._backend.revert_vmn_changes(all_tags)

            return 1

        try:
            self._backend.push(all_tags)
        except Exception:
            LOGGER.exception('Logged Exception message:')
            LOGGER.info('Reverting vmn changes for tags: {0} ...'.format(tags))
            self._backend.revert_vmn_changes(all_tags)

            return 2

        return 0

    def retrieve_remote_changes(self):
        self._backend.pull()


def get_version(versions_be_ifc, pull, init_only):
    if pull:
        versions_be_ifc.retrieve_remote_changes()

    if versions_be_ifc.tracked and init_only:
        raise RuntimeError("Will not init an already tracked app")

    # Here we one of the following:
    # tracked & not init only => normal stamp
    # not tracked & init only => only init a new app
    # not tracked & not init only => init and stamp a new app

    matched_version = versions_be_ifc.find_matching_version()
    if matched_version == '0.0.0.0':
        matched_version = None

    if matched_version is not None:
        # Good we have found an existing version matching
        # the actual_deps_state
        return versions_be_ifc.get_be_formatted_version(matched_version)

    # We didn't find any existing version
    stamped = False
    retries = 3
    override_release_mode = None
    override_current_version = None
    override_main_current_version = None
    current_version = '0.0.0.0'
    main_ver = None

    versions_be_ifc.create_config_files()

    while retries:
        retries -= 1

        if not init_only:
            current_version = versions_be_ifc.stamp_app_version(
                override_release_mode,
                override_current_version,
            )
            main_ver = versions_be_ifc.stamp_main_system_version(
                override_main_current_version,
            )

        err = versions_be_ifc.publish(current_version, main_ver)
        if not err:
            stamped = True
            break

        if err == 1:
            override_current_version = current_version
            override_main_current_version = main_ver
            override_release_mode = versions_be_ifc._release_mode

            LOGGER.warning(
                'Failed to publish. Trying to auto-increase '
                'from {0} to {1}'.format(
                    current_version,
                    gen_app_version(current_version, override_release_mode)
                )
            )
        elif err == 2:
            if not pull:
                break

            time.sleep(random.randint(1, 5))
            versions_be_ifc.retrieve_remote_changes()
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

    vmn_path = os.path.join(params['root_path'], '.vmn')
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_unique_path = os.path.join(vmn_path, changeset)
    Path(vmn_unique_path).touch()
    git_ignore_path = os.path.join(vmn_path, '.gitignore')

    with open(git_ignore_path, 'w+') as f:
        f.write('vmn.lock{0}'.format(os.linesep))

    be.commit(
        message=stamp_utils.INIT_COMMIT_MESSAGE,
        user='vmn',
        include=[vmn_path, vmn_unique_path, git_ignore_path]
    )

    be.push()

    LOGGER.info('Initialized vmn tracking on {0}'.format(params['root_path']))

    return None


def show(params, version=None):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.error('vmn tracking is not yet initialized')
        return 1

    if version is not None:
        if params['root']:
            try:
                int(version)
            except Exception:
                LOGGER.error(
                    'wrong version specified: root version '
                    'must be an integer'
                    )
                return 1
        else:
            try:
                _, _, _, _ = version.split('.')
            except ValueError:
                LOGGER.error(
                    'wrong version specified: version '
                    'must be of form N1.N2.N3.N4'
                    )
                return 1

    tag_name = stamp_utils.VersionControlBackend.get_tag_name(
        params['name'],
        version
    )

    if version is None:
        if params['root']:
            ver_info = be.get_vmn_version_info(
                root_app_name=params['root_app_name']
            )
        else:
            ver_info = be.get_vmn_version_info(app_name=params['name'])
    else:
        ver_info = be.get_vmn_version_info(tag_name=tag_name)

    if ver_info is None:
        LOGGER.error(
            'Version information was not found '
            'for {0}.'.format(
                params['name'],
            )
        )

        return 1

    data = ver_info['stamping']['app']
    if params['root']:
        data = ver_info['stamping']['root_app']
        if not data:
            LOGGER.error(
                'App {0} does not have a root app '.format(
                    params['name'],
                )
            )

            return 1

    if params.get('verbose'):
        yaml.dump(data, sys.stdout)
    elif params.get('raw'):
        print(data['_version'])
    else:
        print(data['version'])

    return 0


def stamp(params, pull=False, init_only=False):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is not yet initialized')
        return err

    err = be.check_for_git_user_config()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    lock_file_path = os.path.join(params['root_app_dir_path'], 'vmn.lock')
    pathlib.Path(os.path.dirname(lock_file_path)).mkdir(
        parents=True, exist_ok=True
    )
    lock = FileLock(lock_file_path)
    with lock:
        LOGGER.info('Locked: {0}'.format(lock_file_path))

        be = VersionControlStamper(params)

        try:
            version = get_version(be, pull, init_only)
        except Exception:
            LOGGER.exception('Logged Exception message:')
            del be

            return 1

        LOGGER.info(version)

        del be
    LOGGER.info('Released locked: {0}'.format(lock_file_path))

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

    if not be.in_detached_head():
        err = be.check_for_outgoing_changes()
        if err:
            LOGGER.info('{0}. Exiting'.format(err))
            return err

    if version is not None:
        if params['root']:
            try:
                int(version)
            except Exception:
                LOGGER.error(
                    'wrong version specified: root version '
                    'must be an integer'
                    )
                return 1
        else:
            try:
                _, _, _, _ = version.split('.')
            except ValueError:
                LOGGER.error(
                    'wrong version specified: version '
                    'must be of form N1.N2.N3.N4'
                    )
                return 1

    tag_name = stamp_utils.VersionControlBackend.get_tag_name(
        params['name'],
        version
    )

    if version is None:
        if params['root']:
            ver_info = be.get_vmn_version_info(
                root_app_name=params['root_app_name']
            )
        else:
            ver_info = be.get_vmn_version_info(app_name=params['name'])
    else:
        ver_info = be.get_vmn_version_info(tag_name=tag_name)

    if ver_info is None:
        LOGGER.error('No such app: {0}'.format(params['name']))
        return 1

    data = ver_info['stamping']['app']
    deps = data["changesets"]
    deps.pop('.')
    if deps:
        if version is None:
            for rel_path, v in deps.items():
                v['hash'] = None

        _goto_version(deps, params['root_path'])

    if version is None:
        be.checkout_branch()
    else:
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

    return 0


def _update_repo(args):
    path, rel_path, changeset = args

    client = None
    try:
        client, err = stamp_utils.get_client(path)
        if client is None:
            return {'repo': rel_path, 'status': 0, 'description': err}
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting update operation because directory {0} '
            'Reason:\n{1}\n'.format(path, exc)
        )

        return {'repo': rel_path, 'status': 1, 'description': None}

    try:
        err = client.check_for_pending_changes()
        if err:
            LOGGER.info('{0}. Aborting update operation '.format(err))
            return {'repo': rel_path, 'status': 1, 'description': err}

    except Exception as exc:
        LOGGER.exception(
            'Skipping "{0}" directory reason:\n{1}\n'.format(path, exc)
        )

        return {'repo': rel_path, 'status': 0, 'description': None}

    try:
        if not client.in_detached_head():
            err = client.check_for_outgoing_changes()
            if err:
                LOGGER.info('{0}. Aborting update operation'.format(err))
                return {'repo': rel_path, 'status': 1, 'description': err}

        LOGGER.info('Updating {0}'.format(rel_path))
        if changeset is None:
            if not client.in_detached_head():
                client.pull()

            rev = client.checkout_branch()

            LOGGER.info('Updated {0} to {1}'.format(rel_path, rev))
        else:
            cur_changeset = client.changeset()
            if not client.in_detached_head():
                client.pull()

            client.checkout(rev=changeset)

            LOGGER.info('Updated {0} to {1}'.format(rel_path, changeset))
    except Exception as exc:
        LOGGER.exception(
            'PLEASE FIX!\nAborting update operation because directory {0} '
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
        if vcs_type == 'git':
            stamp_utils.GitBackend.clone(path, remote)
    except Exception as exc:
        try:
            str = 'already exists and is not an empty directory.'
            if (str in exc.stderr):
                return {'repo': rel_path, 'status': 0, 'description': None}
        except Exception:
            pass

        err = 'Failed to clone {0} repository. ' \
              'Description: {1}'.format(rel_path, exc.args)
        return {'repo': rel_path, 'status': 1, 'description': err}

    return {'repo': rel_path, 'status': 0, 'description': None}


def _goto_version(deps, root):
    args = []
    for rel_path, v in deps.items():
        if v['remote'].startswith('.'):
            v['remote'] = os.path.join(root, v['remote'])
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
        results = p.map(_update_repo, args)

    err = False
    for res in results:
        if res['status'] == 1:
            err = True
            if res['repo'] is None and res['description'] is None:
                continue

            msg = 'Failed to update '
            if res['repo'] is not None:
                msg += ' {0} '.format(res['repo'])
            if res['description'] is not None:
                msg += 'because {0}'.format(res['description'])

            LOGGER.warning(msg)

    if err:
        raise RuntimeError(
            'Failed to update one or more '
            'of the required repos. See log above'
        )


def build_world(name, working_dir, root=False):
    params = {
        'name': name,
        'working_dir': working_dir,
        'root': root
    }

    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        return None

    root_path = os.path.join(be.root())
    params['root_path'] = root_path

    if name is None:
        return params

    app_dir_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
    )
    params['app_dir_path'] = app_dir_path

    app_conf_path = os.path.join(
        app_dir_path,
        'conf.yml'
    )
    params['app_conf_path'] = app_conf_path
    params['repo_name'] = os.path.basename(root_path)

    if root:
        root_app_name = name
    else:
        root_app_name = params['name'].split('/')
        if len(root_app_name) == 1:
            root_app_name = None
        else:
            root_app_name = '/'.join(root_app_name[:-1])

    params['root_app_dir_path'] = app_dir_path
    root_app_conf_path = None
    if root_app_name is not None:
        root_app_dir_path = os.path.join(
            root_path,
            '.vmn',
            root_app_name,
        )

        params['root_app_dir_path'] = root_app_dir_path
        root_app_conf_path = os.path.join(
            root_app_dir_path,
            'root_conf.yml'
        )

    params['root_app_conf_path'] = root_app_conf_path
    params['root_app_name'] = root_app_name

    params['raw_configured_deps'] = {
        os.path.join("../"): {
            os.path.basename(root_path): {
                'remote': be.remote(),
                'vcs_type': be.type()
            }
        }
    }
    params['version_template'] = '{0}.{1}.{2}'
    params["extra_info"] = False
    IVersionsStamper.parse_template(params['version_template'])

    deps = {}
    for rel_path, dep in params['raw_configured_deps'].items():
        deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

    actual_deps_state = HostState.get_actual_deps_state(
        deps,
        root_path
    )
    actual_deps_state['.']['hash'] = be.last_user_changeset()
    params['actual_deps_state'] = actual_deps_state

    if not os.path.isfile(app_conf_path):
        return params

    with open(app_conf_path, 'r') as f:
        data = yaml.safe_load(f)
        params['version_template'] = data["conf"]["template"]
        params["extra_info"] = data["conf"]["extra_info"]
        params['raw_configured_deps'] = data["conf"]["deps"]

        deps = {}
        for rel_path, dep in params['raw_configured_deps'].items():
            deps[os.path.join(root_path, rel_path)] = tuple(dep.keys())

        actual_deps_state.update(
            HostState.get_actual_deps_state(deps, root_path)
        )
        params['actual_deps_state'] = actual_deps_state
        actual_deps_state['.']['hash'] = be.last_user_changeset()

    return params


def main(command_line=None):
    parser = argparse.ArgumentParser('vmn')
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=version_mod.version
    )
    parser.add_argument(
        '--debug',
        required=False,
        action='store_true'
    )
    parser.set_defaults(debug=False)

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
    pshow.add_argument(
        '-v', '--version',
        default=None,
        required=False,
        help="The version to show"
    )
    pshow.add_argument('--root', dest='root', action='store_true')
    pshow.set_defaults(root=False)
    pshow.add_argument('--verbose', dest='verbose', action='store_true')
    pshow.set_defaults(verbose=False)
    pshow.add_argument(
        '--raw', dest='raw', action='store_true'
    )
    pshow.set_defaults(raw=False)

    pstamp = subprasers.add_parser('stamp', help='stamp version')
    pstamp.add_argument(
        '-r', '--release-mode',
        choices=['major', 'minor', 'patch', 'micro'],
        default='patch',
        required=True,
        help='major / minor / patch / micro'
    )
    pstamp.add_argument(
        '-s', '--starting-version',
        default='0.0.0.0',
        required=False,
        help='Starting version'
    )
    pstamp.add_argument('--pull', dest='pull', action='store_true')
    pstamp.set_defaults(pull=False)
    pstamp.add_argument('--init_only', dest='init_only', action='store_true')
    pstamp.set_defaults(init_only=False)
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
    pgoto.add_argument('--root', dest='root', action='store_true')
    pgoto.set_defaults(root=False)
    pgoto.add_argument(
        'name',
        help="The application's name"
    )

    cwd = os.getcwd()
    if 'VMN_WORKING_DIR' in os.environ:
        cwd = os.environ['VMN_WORKING_DIR']

    args = parser.parse_args(command_line)

    global LOGGER
    LOGGER = stamp_utils.init_stamp_logger(args.debug)
    if args.command == 'show':
        LOGGER.disabled = True

    root = False
    if 'root' in args:
        root = args.root

    if 'name' in args:
        prefix = stamp_utils.MOVING_COMMIT_PREFIX
        if args.name.startswith(prefix):
            raise RuntimeError(
                'App name cannot start with {0}'.format(prefix)
            )

        params = build_world(args.name, cwd, root)
    else:
        params = build_world(None, cwd)

    err = 0
    if args.command == 'init':
        err = init(params)
    if args.command == 'show':
        params['verbose'] = args.verbose

        # root app does not have raw version number
        if root:
            params['raw'] = False
        else:
            params['raw'] = args.raw

        LOGGER.disabled = False
        err = show(params, args.version)
    elif args.command == 'stamp':
        params['release_mode'] = args.release_mode
        params['starting_version'] = args.starting_version
        err = stamp(params, args.pull, args.init_only)
    elif args.command == 'goto':
        err = goto_version(params, args.version)

    return err


if __name__ == '__main__':
    err = main()
    if err:
        sys.exit(1)

    sys.exit(0)
