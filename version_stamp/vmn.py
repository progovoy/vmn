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
from version_stamp import version as version_mod


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

        self._version_info_message = {
            'vmn_info': {
                'description_message_version': '1',
                'vmn_version': version_mod.version
            },
            'stamping': {
                'msg': '',
                'app': {},
                'root_app': {}
            }
        }

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

        self._app_conf_path = conf['app_conf_path']

        self._repo_name = '.'

        self._root_app_name = conf['root_app_name']
        self._root_app_conf_path = conf['root_app_conf_path']
        self._extra_info = conf['extra_info']

    def allocate_backend(self):
        self._backend, _ = stamp_utils.get_client(self._root_path)

    def deallocate_backend(self):
        del self._backend

    def find_matching_version(self, user_repo_details):
        tag_name = \
            stamp_utils.VersionControlBackend.get_tag_name(
                self._name,
                version=None
            )

        # Try to find any version of the application matching the
        # user's repositories local state
        for tag in self._backend.tags():
            if not tag.startswith(tag_name):
                continue

            ver_info = self._backend.get_vmn_version_info(tag)
            if ver_info is None:
                continue

            found = True
            for k, v in ver_info['stamping']['app']['changesets'].items():
                if k not in user_repo_details:
                    found = False
                    break

                # when k is the "main repo" repo
                if self._repo_name == k:
                    user_changeset = \
                        self._backend.last_user_changeset()

                    if v['hash'] != user_changeset:
                        found = False
                        break
                elif v['hash'] != user_repo_details[k]['hash']:
                    found = False
                    break

            if found:
                return ver_info['stamping']['app']['_version']

        return None

    def _write_app_conf_file(self, deps):
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

    def _write_root_conf_file(self, external_services):
        ver_yml = {
            "conf": {
                'external_services': external_services
            },
        }

        with open(self._root_app_conf_path, 'w+') as f:
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

        branch_name = self._backend.get_active_branch()
        tag_name = stamp_utils.VersionControlBackend.get_moving_tag_name(
            self._name, branch_name)
        ver_info = self._backend.get_vmn_version_info(tag_name)
        if ver_info is None:
            old_version = starting_version
        else:
            old_version = ver_info['stamping']['app']["_version"]

        if override_current_version is None:
            override_current_version = old_version

        current_version = gen_app_version(
            override_current_version, override_release_mode
        )

        # If there is no file - create it
        if not os.path.isfile(self._app_conf_path):
            pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
                parents=True, exist_ok=True
            )
            self._write_app_conf_file(deps={})

        flat_dependency_repos = []
        configured_deps = {}
        with open(self._app_conf_path) as f:
            data = yaml.safe_load(f)
            configured_deps = data["conf"]["deps"]

            # resolve relative paths
            for rel_path, v in configured_deps.items():
                for repo in v:
                    flat_dependency_repos.append(
                        os.path.relpath(
                            os.path.join(
                                self._backend.root(), rel_path, repo
                            ),
                            self._backend.root()
                        ),
                    )

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

        self._write_app_conf_file(deps=configured_deps)

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

        changesets_to_file = {}
        for k in flat_dependency_repos:
            if self._repo_name == k:
                changesets_to_file[k] = user_repo_details[k]
                changesets_to_file[k]['hash'] = \
                    self._backend.last_user_changeset()
            else:
                changesets_to_file[k] = user_repo_details[k]

        info = {}
        if self._extra_info:
            info['env'] = dict(os.environ)

        self._version_info_message['stamping']['app'] = {
            'name': self._name,
            'version': IVersionsStamper.get_formatted_version(
                current_version,
                self._version_template,
                self._version_template_octats_count),
            '_version': current_version,
            "release_mode": self._release_mode,
            "previous_version": old_version,
            "changesets": changesets_to_file,
            "info": info,
        }

        return current_version

    def stamp_main_system_version(self, override_version=None):
        if self._root_app_name is None:
            return None

        # If there is no file - create it
        if not os.path.isfile(self._root_app_conf_path):
            pathlib.Path(os.path.dirname(self._app_conf_path)).mkdir(
                parents=True, exist_ok=True
            )
            self._write_root_conf_file(external_services={})

        branch_name = self._backend.get_active_branch()
        tag_name = stamp_utils.VersionControlBackend.get_moving_tag_name(
            self._root_app_name, branch_name)
        ver_info = self._backend.get_vmn_version_info(tag_name)
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
            'name': self._root_app_name,
            'version': root_version,
            'latest_service': self._name,
            'services': services,
            'external_services': external_services,
        }

        msg_root_app = self._version_info_message['stamping']['root_app']
        msg_app = self._version_info_message['stamping']['app']
        msg_root_app['services'][self._name] = msg_app['_version']

        return '{0}'.format(root_version)

    def publish(self, app_version, main_version=None):
        version_files = [
            self._app_conf_path
        ]
        if self._root_app_name is not None:
            version_files.append(self._root_app_conf_path)

        self._version_info_message['stamping']['msg'] = \
            '{0}: update to version {1}'.format(
                self._name, app_version
            )
        msg = yaml.dump(self._version_info_message, sort_keys=False)
        self._backend.commit(
            message=msg,
            user='vmn',
            include=version_files
        )

        tags = [stamp_utils.VersionControlBackend.get_tag_name(
            self._name, app_version)
        ]

        branch_name = self._backend.get_active_branch()
        latest_branch_tag_name = stamp_utils.VersionControlBackend.\
            get_moving_tag_name(self._name, branch_name)
        moving_tags = [latest_branch_tag_name]

        if main_version is not None:
            tags.append(
                stamp_utils.VersionControlBackend.get_tag_name(
                    self._root_app_name, main_version)
            )
            latest_branch_tag_name = stamp_utils.VersionControlBackend. \
                get_moving_tag_name(self._root_app_name, branch_name)
            moving_tags.append(latest_branch_tag_name)

        all_tags = []
        all_tags.extend(tags)
        all_tags.extend(moving_tags)

        try:
            self._backend.tag(tags, user='vmn')
            self._backend.tag(moving_tags, user='vmn', force=True)
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


def get_version(versions_be_ifc, params, pull):
    if pull:
        versions_be_ifc.retrieve_remote_changes()

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
            override_release_mode = 'micro'

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
        return 1

    branch_name = be.get_active_branch()
    tag_name = stamp_utils.VersionControlBackend.get_moving_tag_name(
        params['name'], branch_name)
    ver_info = be.get_vmn_version_info(tag_name)

    if ver_info is None:
        LOGGER.error(
            'Version file was not found '
            'for {0}. Tag: "{1}"'.format(
                params['name'],
                tag_name
            )
        )

        return 1

    data = ver_info['stamping']['app']
    if params['root']:
        data = ver_info['stamping']['root_app']

    if params['verbose']:
        yaml.dump(data, sys.stdout)
    elif params['raw']:
        print(data['_version'])
    else:
        print(data['version'])

    return 0


def stamp(params, pull=False):
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

    lock_file_path = os.path.join(params['root_path'], 'vmn.lock')
    lock = FileLock(lock_file_path)
    with lock:
        LOGGER.info('Locked: {0}'.format(lock_file_path))

        be = VersionControlStamper(params)

        be.allocate_backend()

        try:
            version = get_version(be, params, pull)
        except Exception:
            LOGGER.exception('Logged Exception message:')
            be.deallocate_backend()

            return 1

        LOGGER.info(version)

        be.deallocate_backend()

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

    err = be.check_for_outgoing_changes(skip_detached_check=True)
    if err:
        LOGGER.info('{0}. Exiting'.format(err))
        return err

    if version is None:
        branch_name = be.get_active_branch(raise_on_detached_head=False)
        tag_name = stamp_utils.VersionControlBackend.get_moving_tag_name(
            params['name'], branch_name
        )
    else:
        tag_name = stamp_utils.VersionControlBackend.get_tag_name(
            params['name'], version
        )

    ver_info = be.get_vmn_version_info(tag_name)

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

    app_conf_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
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

    root_app_conf_path = None
    if root_app_name is not None:
        root_app_conf_path = os.path.join(
            root_path,
            '.vmn',
            root_app_name,
            'root_conf.yml'
        )

    params['root_app_conf_path'] = root_app_conf_path
    params['root_app_name'] = root_app_name

    default_repos_path = os.path.join(root_path, '../')
    user_repos_details = HostState.get_user_repo_details(
        {default_repos_path: os.listdir(default_repos_path)},
        root_path
    )
    params['version_template'] = '{0}.{1}.{2}'
    params["extra_info"] = False
    params['user_repos_details'] = user_repos_details

    if not os.path.isfile(app_conf_path):
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
        default='micro',
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
    pstamp.add_argument(
        'name', help="The application's name"
    )
    pstamp.set_defaults(pull=False)

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
        params['raw'] = args.raw
        err = show(params)
    elif args.command == 'stamp':
        params['release_mode'] = args.release_mode
        params['starting_version'] = args.starting_version
        err = stamp(params, args.pull)
    elif args.command == 'goto':
        err = goto_version(params, args.version)

    return err


if __name__ == '__main__':
    err = main()
    if err:
        sys.exit(1)

    sys.exit(0)
