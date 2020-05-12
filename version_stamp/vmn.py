#!/usr/bin/env python3
import argparse
from pathlib import Path
import copy
import yaml
import json
import sys
import os
import logging
import pathlib
import importlib.machinery
import types
from lockfile import LockFile
import time

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

    def stamp_app_version(self, current_changesets, extra_info=False):
        raise NotImplementedError('Please implement this method')

    def stamp_main_system_version(self, service_version):
        raise NotImplementedError('Please implement this method')

    def publish(self, app_version, main_version=None):
        raise NotImplementedError('Please implement this method')


class VersionControlStamper(IVersionsStamper):
    def __init__(self, conf):
        IVersionsStamper.__init__(self, conf)

        self._app_version_file = conf['app_path']

        self._app_path = os.path.dirname(self._app_version_file)
        self._app_version_history_path = \
            os.path.join(self._app_path, '_version_history.py')
        self._repo_name = conf['repo_name']

        self._main_system_name = conf['main_system_name']
        self._main_version_file = conf['main_version_file']

        self._main_version_history_path = None
        if self._main_version_file is not None:
            root_ver_path = os.path.dirname(self._main_version_file)
            self._main_version_history_path = \
                os.path.join(root_ver_path, '_main_version_history.py')

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

    def _write_app_version_file(self, version, changesets, release_mode, extra_info=False):
        info = {}
        if extra_info:
            info['env'] = dict(os.environ)

        ver_yml = {
            'name': self._name,
            'display_name': self._name,
            'version': IVersionsStamper.get_formatted_version(
                version,
                self._version_template,
                self._version_template_octats_count),
            '_version': version,
            "template": self._version_template,
            "release_mode": release_mode,
            "changesets": changesets,
            "conf": {
                "deps": {
                    "../": [os.path.basename(self._root_path)]
                },
                "extra_info": extra_info,
            },
            "info": info
        }
        with open(self._app_version_file, 'w+') as f:
            f.write('# Autogenerated by vmn. Do not edit\n')
            documents = yaml.dump(ver_yml, f, sort_keys=False)

    def _get_underlying_services(self):
        path = os.path.join(
            self._backend.root(),
            self._main_system_name
        )

        underlying_apps = {}
        for dir in os.listdir(path):
            with open(self._app_version_file) as f:
                data = yaml.safe_load(f)
                underlying_apps['{0}/{1}'.format(path, dir)] = data['_version']

        return underlying_apps

    def _write_root_version_file(self, version):
        ver_yml = {
            'name': self._main_system_name,
            'display_name': self._main_system_name,
            'version': IVersionsStamper.get_formatted_version(
                version,
                self._root_version_template,
                self._root_version_template_octats_count),
            '_version': version,
            "template": self._root_version_template,
            "services": self._get_underlying_services(),
            "release_mode": self._release_mode,
            "conf": {'external_services': {}},
        }
        with open(self._main_version_file, 'w+') as f:
            f.write('# Autogenerated by vmn. Do not edit\n')
            documents = yaml.dump(ver_yml, f, sort_keys=False)

    def stamp_app_version(self, current_changesets, extra_info=False):
        # If there is no file - create it
        if not os.path.isfile(self._app_version_file):
            pathlib.Path(self._app_path).mkdir(parents=True, exist_ok=True)

            self._write_app_version_file(
                version="0.0.0",
                release_mode='init',
                changesets={},
            )

        # If there is no file - create it
        if not os.path.isfile(self._app_version_history_path):
            with open(self._app_version_history_path, 'w+') as f:
                f.write('# Autogenerated by version stamper. Do not edit\n')
                f.write('changesets = {}\n')

        with open(self._app_version_file) as f:
            data = yaml.safe_load(f)
            custom_repos = data["conf"]["deps"]["../"]
            old_version = data["_version"]
            old_changesets = copy.deepcopy(data["changesets"])

        loader = importlib.machinery.SourceFileLoader(
            '_version_history', self._app_version_history_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        hist_changesets = mod_ver.changesets

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
        with open(self._app_version_file, "w+") as f:
            changesets_to_file = current_changesets
            if custom_repos:
                changesets_to_file = {}
                for k in custom_repos:
                    changesets_to_file[k] = current_changesets[k]



            self._write_app_version_file(
                version=current_version,
                changesets=changesets_to_file,
                release_mode=self._release_mode,
                extra_info=extra_info
            )

        # may happen in case of recurring version
        if not old_changesets:
            return current_version

        hist_changesets[old_version] = old_changesets

        # write service version history
        with open(self._app_version_history_path, "w+") as f:
            f.write('# Autogenerated by version stamper. Do not edit\n')
            f.write('changesets = {\n')
            f.write(json.dumps(hist_changesets)[1:-1])
            f.write('}\n')

        return current_version

    def stamp_main_system_version(self, service_version):
        if self._main_system_name is None:
            return None

        if not os.path.isfile(self._main_version_file):
            self._write_root_version_file(version='0.0.0')

        if not os.path.isfile(self._main_version_history_path):
            with open(self._main_version_history_path, 'w+') as f:
                f.write('# Autogenerated by version stamper. Do not edit\n')
                f.write('services = {}\n')
                f.write('external_services = {}\n')

        with open(self._main_version_file) as f:
            data = yaml.safe_load(f)
            template = data['template']
            old_services = copy.deepcopy(data['services'])
            old_version = data["_version"]
            old_external_services = copy.deepcopy(
                data['conf']['external_services']
            )

        loader = importlib.machinery.SourceFileLoader(
            '_main_version_history', self._main_version_history_path)
        mod_ver = types.ModuleType(loader.name)
        loader.exec_module(mod_ver)
        hist_services = mod_ver.services
        hist_external_services = mod_ver.external_services

        root_version = gen_app_version(
            old_version, self._release_mode
        )

        if self._release_mode == 'debug':
            return root_version

        self._write_root_version_file(version=root_version)

        hist_services[old_version] = old_services
        hist_external_services[old_version] = old_external_services

        # write service main version history
        with open(self._main_version_history_path, "w+") as f:
            f.write('# Autogenerated by version stamper. Do not edit\n')
            f.write('services = {\n')
            f.write(json.dumps(hist_services)[1:-1])
            f.write('}\n')

            f.write('external_services = {\n')
            f.write(json.dumps(hist_external_services)[1:-1])
            f.write('}\n')

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
            self._app_version_file,
            self._app_version_history_path
        ]
        if self._main_system_name is not None:
            version_files.append(self._main_version_file)
            version_files.append(self._main_version_history_path)

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
            s = os.path.split(self._main_system_name)
            if not s[0]:
                tags.append('{0}_{1}'.format(self._main_system_name, main_version))
            else:
                tags.append(
                    '{0}_{1}'.format('-'.join(s), main_version)
                )

        self._backend.tag(tags, user='version_manager')

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
        app_ver_dir_path = os.path.dirname(self._app_version_file)
        app_hist_ver_path = os.path.join(app_ver_dir_path,
                                         '_version_history.py')

        if not os.path.isfile(self._app_version_file):
            return None, None, None

        with open(self._app_version_file) as f:
            data = yaml.safe_load(f)
            current_changesets = data['changesets']
            version = data['_version']

        if os.path.isfile(app_hist_ver_path):
            loader = importlib.machinery.SourceFileLoader(
                '_version_history', app_hist_ver_path)
            mod_ver = types.ModuleType(loader.name)
            loader.exec_module(mod_ver)

            try:
                hist_changesets = mod_ver.changesets
            except AttributeError:
                pass

        tags = self._backend.tags()
        tag_ver = None
        # Find the first tag with app_name
        for tag in tags:
            # Find the last occurrence of '_' in the tag and extract an
            # app name from it
            tag = tag.replace('-', '/')
            tmp = tag[:tag.rfind('_')]
            if not tmp == self._name:
                continue

            tag_ver = tag.split('{0}_'.format(self._name))[1]
            break

        if tag_ver != version:
            LOGGER.warning(
                "WARNING: Version file path: {0} found but "
                "app tag is not equal to the version "
                "or is corrupted. This requires manual "
                "intervention (vers retag app-name)."
                "Probably someone removed app's tag or "
                "changed it. "
                "tag found: {1} the version: {2}".format(
                    self._app_version_file,
                    tag_ver,
                    version
                )
            )

        return version, current_changesets, hist_changesets


def get_version(versions_be_ifc, current_changesets, extra_info=False):
    ver = versions_be_ifc.find_version(current_changesets)
    if ver is not None:
        # Good we have found an existing version matching
        # the current_changesets
        return versions_be_ifc.get_be_formatted_version(ver)

    # We didn't find any existing version - generate new one
    current_version = versions_be_ifc.stamp_app_version(
        current_changesets, extra_info
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

    changeset, type = HostState.get_changeset(be.root())

    vmn_path = '{0}/.vmn/'.format(be.root())
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_unique_path = '{0}/{1}_{2}'.format(
        vmn_path,
        os.path.basename(be.root()),
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

    root_path = os.path.join(be.root())
    app_path = os.path.join(
        root_path,
        '.vmn',
        params['name'],
        'ver.yml'
    )
    app_dir_path = os.path.dirname(app_path)
    params['root_path'] = root_path
    params['app_path'] = app_path
    params['repo_name'] = os.path.basename(root_path)

    main_system_name = params['name'].split('/')
    if len(main_system_name) == 1:
        main_system_name = None
    else:
        main_system_name = '/'.join(main_system_name[:-1])

    main_version_file = None
    if main_system_name is not None:
        main_version_file = os.path.join(
            root_path,
            '.vmn',
            main_system_name,
            'root_ver.yml'
        )

    params['main_system_name'] = main_system_name
    params['main_version_file'] = main_version_file

    if not os.path.isfile(app_path):
        pathlib.Path(app_dir_path).mkdir(parents=True, exist_ok=True)
        default_repos_path = os.path.join(root_path, '../')
        changesets = HostState.get_current_changeset(
            {default_repos_path: os.listdir(default_repos_path)}
        )
        params['version_template'] = '{0}.{1}.{2}'
        params['root_version_template'] = '{0}.{1}.{2}'
        params["extra_info"] = False
    else:
        with open(app_path) as f:
            data = yaml.safe_load(f)
            params['version_template'] = data["template"]
            params["extra_info"] = data["conf"]["extra_info"]

            params['root_version_template'] = None
            if main_version_file is not None and os.path.isfile(main_version_file):
                with open(main_version_file) as root_f:
                    root_data = yaml.safe_load(root_f)
                    params['root_version_template'] = root_data["template"]

            deps = {}
            for dep,lst in data["conf"]["deps"].items():
                deps[os.path.join(root_path, dep)] = lst

            changesets = HostState.get_current_changeset(deps)

    lock = LockFile(os.path.join(root_path, 'vmn.lock'))
    with lock:
        LOGGER.info('Locked: {0}'.format(lock.path))

        be = VersionControlStamper(params)

        be.allocate_backend()

        version = get_version(be, changesets, params["extra_info"])
        LOGGER.info(version)

        be.deallocate_backend()

    LOGGER.info('Released locked: {0}'.format(lock.path))

    return 0


def _enhance_params(params):
    params['name'] = os.path.split(params['name'])
    params['name'] = os.path.join(*params['name'])


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

    args = parser.parse_args(command_line)
    params = copy.deepcopy(vars(args))
    if args.command == 'init':
        init()
    if args.command == 'show':
        show(args.name)
    elif args.command == 'stamp':
        _enhance_params(params)
        stamp(params)


if __name__ == '__main__':
    main()
