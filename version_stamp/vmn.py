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
from packaging import version as pversion


CUR_PATH = '{0}/'.format(os.path.dirname(__file__))
VER_FILE_NAME = 'last_known_app_version.yml'
sys.path.append(CUR_PATH)
import stamp_utils
from stamp_utils import HostState
import version as version_mod

LOGGER = stamp_utils.init_stamp_logger()


class IVersionsStamper(object):
    def __init__(self, conf):
        self._name = conf['name']
        self._root_path = conf['root_path']
        self._backend, _ = stamp_utils.get_client(self._root_path)
        self._release_mode = conf['release_mode']
        self._app_dir_path = conf['app_dir_path']
        self._app_conf_path = conf['app_conf_path']
        self._starting_version = conf['starting_version']
        self._mode = conf['mode']
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
        self._mode_count = {}
        self._current_mode = 'release'

        self.ver_info_form_repo = \
            self.get_vmn_version_info(
                app_name=self._name
            )
        self.tracked = self.ver_info_form_repo is not None
        if self.tracked:
            self._mode_count = self.ver_info_form_repo['stamping']['app']["mode_count"]
            self._current_mode = self.ver_info_form_repo['stamping']['app']["orig_current_mode"]

        if self._current_mode == 'release' and self._release_mode is None:
            del self._backend

            raise RuntimeError(
                'When stamping from a previous release version '
                'a release mode must be specified'
            )

        self._releasing_rc = (
                self._current_mode != 'release' and
                self._release_mode is None and
                self._mode == 'release'
        )
        self._should_publish = True

        self._version_info_message = {
            'vmn_info': {
                'description_message_version': '1.1',
                'vmn_version': version_mod.version
            },
            'stamping': {
                'msg': '',
                'app': {
                    'name': self._name,
                    'changesets': self.actual_deps_state,
                    'version': self.get_formatted_version('0.0.0'),
                    '_version': '0.0.0',
                    'release_mode': self._release_mode,
                    "previous_version": '0.0.0',
                    'current_mode': 'release',
                    'mode_count': {},
                    "info": {},
                },
                'root_app': {}
            }
        }

        if self.tracked and self._release_mode is None:
            self._version_info_message['stamping']['app']['release_mode'] = \
                self.ver_info_form_repo['stamping']['app']['release_mode']

        if self._root_app_name is not None:
            self._version_info_message['stamping']['root_app'] = {
                'name': self._root_app_name,
                'version': 0,
                'latest_service': self._name,
                'services': {self._name: '0.0.0'},
                'external_services': {},
            }

    def __del__(self):
        del self._backend

    def gen_app_version(self, current_version):
        major, minor, suffix = current_version.split('.')
        patch = suffix
        mode = self._mode
        mode_count = self._mode_count

        # If user did not specify a change in mode,
        # stay with the previous one
        if mode is None:
            mode = self._current_mode

        if self._current_mode != 'release' and self._release_mode is None:
            patch, cur_rc = suffix.split('_')

            if mode not in mode_count:
                mode_count[mode] = 0
            mode_count[mode] += 1

            self._version_info_message['stamping']['app']['mode_count'] = mode_count
            self._version_info_message['stamping']['app']['current_mode'] = mode
        elif self._current_mode != 'release' and self._release_mode is not None and mode != 'release':
            patch, _ = suffix.split('_')
            mode_count = {
                mode: 1
            }

            self._version_info_message['stamping']['app']['mode_count'] = mode_count
            self._version_info_message['stamping']['app']['current_mode'] = mode
        elif self._current_mode == 'release' and mode != 'release':
            mode_count = {
                mode: 1
            }

            self._version_info_message['stamping']['app']['mode_count'] = mode_count
            self._version_info_message['stamping']['app']['current_mode'] = mode

        if self._release_mode == 'major':
            major = str(int(major) + 1)
            minor = str(0)
            patch = str(0)
        elif self._release_mode == 'minor':
            minor = str(int(minor) + 1)
            patch = str(0)
        elif self._release_mode == 'patch':
            patch = str(int(patch) + 1)

        verstr = '{0}.{1}.{2}'.format(major, minor, patch)
        if mode != 'release':
            verstr = '{0}_{1}-{2}'.format(verstr, mode, mode_count[mode])

        return verstr

    @staticmethod
    def parse_template(template):
        placeholders = (
            '{0}', '{1}', '{2}', '{NON_EXISTING_PLACEHOLDER}'
        )
        templates = [None, None, None]

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
        for t in templates:
            if t is None:
                break

            ver_format += t
            octats_count += 1

        return ver_format, octats_count

    def get_formatted_version(self, version):
        octats = version.split('.')
        if len(octats) > 3:
            raise RuntimeError('Version is too long. Maximum is 3 octats')

        for i in range(3 - len(octats)):
            octats.append('0')

        return self._version_template.format(*(octats[:self._version_template_octats_count]))

    def get_vmn_version_info(
            self,
            tag_name=None,
            app_name=None,
            root_app_name=None
    ):
        formated_tag_name = None
        if tag_name is None and app_name is None and root_app_name is None:
            return None

        commit_tag_obj = None
        if tag_name is not None:
            try:
                commit_tag_obj = self._backend._be.commit(tag_name)
            except:
                return None
        elif app_name is not None or root_app_name is not None:
            used_app_name = app_name
            root = False
            if root_app_name is not None:
                used_app_name = root_app_name
                root = True

            max_version = None
            formated_tag_name = stamp_utils.VersionControlBackend.get_tag_name(
                used_app_name
            )
            tags = self._backend.tags(filter='{}_*'.format(formated_tag_name))

            for tag in tags:
                _app_name, version, mode_version = stamp_utils.VersionControlBackend.get_tag_properties(
                    tag, root=root
                )
                if version is None:
                    continue

                if _app_name != used_app_name:
                    continue

                _commit_tag_obj = self._backend._be.commit(tag)
                if _commit_tag_obj.author.name != stamp_utils.VMN_USER_NAME:
                    continue

                if max_version is None:
                    max_version = version
                    tag_name = tag
                    commit_tag_obj = _commit_tag_obj
                elif pversion.parse(max_version) < pversion.parse(version):
                    max_version = version
                    tag_name = tag
                    commit_tag_obj = _commit_tag_obj

        if commit_tag_obj is None:
            return None

        if commit_tag_obj.author.name != stamp_utils.VMN_USER_NAME:
            return None

        # TODO:: Check API commit version

        commit_msg = yaml.safe_load(
            self._backend._be.commit(tag_name).message
        )

        if commit_msg is None or 'stamping' not in commit_msg:
            # TODO: raise error here?
            return None

        commit_msg['stamping']['app']['orig_current_mode'] = \
            commit_msg['stamping']['app']['current_mode']

        tmp_ver = tag_name.replace(
            '{0}_'.format(commit_msg['stamping']['app']['name']),
            ''
        )
        if commit_msg['stamping']['app']['_version'].startswith(tmp_ver) and \
           commit_msg['stamping']['app']['_version'] != tmp_ver:
           prev_ver = commit_msg['stamping']['app']['_version']
           commit_msg['stamping']['app']['_version'] = tmp_ver
           commit_msg['stamping']['app']['current_mode'] = 'release'
           commit_msg['stamping']['app']['previous_version'] = prev_ver
           commit_msg['stamping']['app']['version'] = \
               self.get_formatted_version(tmp_ver)

        return commit_msg

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
        return self.get_formatted_version(version)

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
                version=None,
            )

        # Try to find any version of the application matching the
        # user's repositories local state
        for tag in self._backend.tags():
            if not re.match(
                r'{}_(\d+\.\d+\.\d+)_?(.+[0-9]+)*$'.format(app_tag_name),
                tag
            ):
                continue

            ver_info = self.get_vmn_version_info(tag_name=tag)
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

            if found and self._mode == 'release' and ver_info['stamping']['app']['current_mode'] != 'release':
                return None
            elif found:
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
        only_initialized = self.tracked and \
            self.ver_info_form_repo['stamping']['app']['_version'] == '0.0.0'

        if only_initialized or not self.tracked:
            # first stamp
            return self._starting_version

        version = self.ver_info_form_repo['stamping']['app']["_version"]
        version_str_from_file = self.get_version_number_from_file()
        if version_str_from_file:
            version = version_str_from_file

        return version

    def stamp_app_version(
            self,
            override_current_version=None,
    ):
        old_version = self.decide_app_version_by_source()
        if self._releasing_rc:
            self._should_publish = False
            tag_name = stamp_utils.VersionControlBackend.get_tag_name(
                self._name, old_version
            )
            if self._backend.changeset() != self._backend.changeset(tag=tag_name):
                raise RuntimeError(
                    'Releasing a release candidate is only possile when the repository '
                    'state is on the exact version. Please vmn goto the version you\'d '
                    'like to release.'
                )

            _, version, _ = \
                stamp_utils.VersionControlBackend.get_tag_properties(
                    tag_name
                )

            tag_name = stamp_utils.VersionControlBackend.get_tag_name(
                self._name, version
            )

            self._backend.tag([tag_name], user='vmn', force=True)

            return version

        matched_version = self.find_matching_version()
        if matched_version == '0.0.0':
            matched_version = None

        if matched_version is not None:
            # Good we have found an existing version matching
            # the actual_deps_state
            self._should_publish = False

            return self.get_be_formatted_version(matched_version)

        if override_current_version is None:
            override_current_version = old_version

        # TODO:: optimization find max here

        current_version = self.gen_app_version(
            override_current_version,
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
            self.get_formatted_version(current_version)
        self._version_info_message['stamping']['app']['_version'] = \
            current_version
        self._version_info_message['stamping']['app']['previous_version'] = \
            old_version
        self._version_info_message['stamping']['app']['info'] = \
            info
        self._version_info_message['stamping']['app']['stamped_on_branch'] =\
            self._backend.get_active_branch()

        return current_version

    def stamp_main_system_version(
            self,
            override_version=None,
    ):
        if self._root_app_name is None:
            return None

        ver_info = self.get_vmn_version_info(
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
        if not self._should_publish:
            return 0

        version_files = [self._app_conf_path]
        if app_version != '0.0.0':
            version_files.append(self._version_file_path)
        if self._root_app_name is not None:
            version_files.append(self._root_app_conf_path)

        self._version_info_message['stamping']['msg'] = \
            '{0}: update to version {1}'.format(
                self._name, app_version
            )
        msg = yaml.dump(self._version_info_message, sort_keys=True)
        self._backend.commit(
            message=msg,
            user='vmn',
            include=version_files
        )

        tags = [stamp_utils.VersionControlBackend.get_tag_name(
            self._name, app_version
        )]

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

    # We didn't find any existing version
    stamped = False
    retries = 3
    override_current_version = None
    override_main_current_version = None
    current_version = '0.0.0'
    main_ver = None

    versions_be_ifc.create_config_files()

    while retries:
        retries -= 1

        if not init_only:
            current_version = versions_be_ifc.stamp_app_version(
                override_current_version,
            )
            main_ver = versions_be_ifc.stamp_main_system_version(
                override_main_current_version,
            )

        # TODO:: handle case where init_only was set for an existing app

        err = versions_be_ifc.publish(current_version, main_ver)
        if not err:
            stamped = True
            break

        if err == 1:
            override_current_version = current_version
            override_main_current_version = main_ver

            LOGGER.warning(
                'Failed to publish. Trying to auto-increase '
                'from {0} to {1}'.format(
                    current_version,
                    versions_be_ifc.gen_app_version(current_version)
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
        del be
        return err

    if os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is already initialized')
        del be
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        del be
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        del be
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
    del be

    LOGGER.info('Initialized vmn tracking on {0}'.format(params['root_path']))

    return None


def show(vcs, params, version=None):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        del be
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.error('vmn tracking is not yet initialized')
        del be
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
                del be
                return 1
        else:
            try:
                _, _, _ = version.split('.')
            except ValueError:
                LOGGER.error(
                    'wrong version specified: version '
                    'must be of form N1.N2.N3'
                    )
                del be
                return 1

    tag_name = stamp_utils.VersionControlBackend.get_tag_name(
        params['name'],
        version,
    )

    if version is None:
        if params['root']:
            ver_info = vcs.get_vmn_version_info(
                root_app_name=params['root_app_name']
            )
        else:
            ver_info = vcs.get_vmn_version_info(app_name=params['name'])
    else:
        ver_info = vcs.get_vmn_version_info(tag_name=tag_name)

    if ver_info is None:
        LOGGER.error(
            'Version information was not found '
            'for {0}.'.format(
                params['name'],
            )
        )
        del be

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
            del be

            return 1

    if params.get('verbose'):
        yaml.dump(data, sys.stdout)
    elif params.get('raw'):
        print(data['_version'])
    else:
        print(data['version'])

    del be

    return 0


def stamp(versions_be_ifc, params, pull=False, init_only=False):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        del be
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is not yet initialized')
        del be
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        del be
        return err

    err = be.check_for_outgoing_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        del be
        return err

    del be

    lock_file_path = os.path.join(params['root_app_dir_path'], 'vmn.lock')
    pathlib.Path(os.path.dirname(lock_file_path)).mkdir(
        parents=True, exist_ok=True
    )
    lock = FileLock(lock_file_path)

    with lock:
        LOGGER.info('Locked: {0}'.format(lock_file_path))

        version = get_version(versions_be_ifc, pull, init_only)
        try:
            pass
        except Exception as exc:
            LOGGER.exception('Logged Exception message:')

            return 1

        LOGGER.info(version)

    LOGGER.info('Released locked: {0}'.format(lock_file_path))


def goto_version(vcs, params, version):
    be, err = stamp_utils.get_client(params['working_dir'])
    if err:
        LOGGER.error('{0}. Exiting'.format(err))
        del be
        return err

    if not os.path.isdir('{0}/.vmn'.format(params['root_path'])):
        LOGGER.info('vmn tracking is not yet initialized')
        del be
        return err

    err = be.check_for_pending_changes()
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        del be
        return err

    if not be.in_detached_head():
        err = be.check_for_outgoing_changes()
        if err:
            LOGGER.info('{0}. Exiting'.format(err))
            del be
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
                del be

                return 1
        else:
            try:
                _, _, _ = version.split('.')
            except ValueError:
                LOGGER.error(
                    'wrong version specified: version '
                    'must be of form N1.N2.N3'
                    )
                del be

                return 1

    tag_name = stamp_utils.VersionControlBackend.get_tag_name(
        params['name'],
        version,
    )

    if version is None:
        if params['root']:
            ver_info = vcs.get_vmn_version_info(
                root_app_name=params['root_app_name']
            )
        else:
            ver_info = vcs.get_vmn_version_info(app_name=params['name'])
    else:
        ver_info = vcs.get_vmn_version_info(tag_name=tag_name)

    if ver_info is None:
        LOGGER.error('No such app: {0}'.format(params['name']))
        del be
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
            del be

            return 1

    del be

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
    # TODO: handle redundant parse template here
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
    pshow.add_argument('-m', '--mode')
    pshow.add_argument('-mv', '--mode_version', default=None)
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
        choices=['major', 'minor', 'patch'],
        default=None,
        help='major / minor / patch'
    )
    pstamp.add_argument(
        '-m', '--mode',
        default=None,
        help='Version mode. Can be anything really until you decide '
             'to set the mode to be release again'
    )
    pstamp.add_argument(
        '-s', '--starting-version',
        default='0.0.0',
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
    pgoto.add_argument('-m', '--mode')
    pgoto.add_argument('-mv', '--mode_version', default=None)
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
        # root app does not have raw version number
        if root:
            params['raw'] = False
        else:
            params['raw'] = args.raw

        params['verbose'] = args.verbose

        LOGGER.disabled = False
        version = args.version
        if version is not None and \
                args.mode is not None and \
                args.mode_version is not None:
            version = '{0}_{1}-{2}'.format(
                version,
                args.mode,
                args.mode_version
            )

        # TODO: handle cmd specific params differently
        params['release_mode'] = None
        params['starting_version'] = '0.0.0'
        params['mode'] = None
        vcs = VersionControlStamper(params)
        err = show(vcs, params, version)
        del vcs
    elif args.command == 'stamp':
        params['release_mode'] = args.release_mode
        params['starting_version'] = args.starting_version
        params['mode'] = args.mode
        vcs = VersionControlStamper(params)
        err = stamp(vcs, params, args.pull, args.init_only)
        del vcs
    elif args.command == 'goto':
        version = args.version
        if args.mode is not None and args.mode_version is not None:
            version = '{0}_{1}-{2}'.format(
                version,
                args.mode,
                args.mode_version
            )

        vcs = VersionControlStamper(params)
        err = goto_version(vcs, params, version)
        del vcs

    return err


if __name__ == '__main__':
    err = main()
    if err:
        sys.exit(1)

    sys.exit(0)
