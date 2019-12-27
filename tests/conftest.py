import pytest
import hglib
import uuid
import os
import sys
import logging
import pathlib
import shutil
import json
from git import Repo

sys.path.append('{0}/../version_stamp'.format(os.path.dirname(__file__)))
import ver_stamp
import stamp_utils

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)
format = '[%(asctime)s.%(msecs)03d] [%(name)s] [%(levelname)s] ' \
         '%(message)s'

formatter = logging.Formatter(format, '%Y-%m-%d %H:%M:%S')

cons_handler = logging.StreamHandler(sys.stdout)
cons_handler.setFormatter(formatter)
LOGGER.addHandler(cons_handler)


class FSAppLayoutFixture(object):
    def __init__(self, versions, remote_versions, be_type):
        self.versions_root_path = versions.strpath
        self.versions_base_dir = versions.dirname
        self._repos = {}

        if be_type == 'mercurial':
            self._versions_backend = MercurialBackend(
                remote_versions.strpath,
                versions.strpath
            )

            self.be_class = ver_stamp.VersionControlStamper
        elif be_type == 'git':
            self._versions_backend = GitBackend(
                remote_versions.strpath,
                versions.strpath
            )

            self.be_class = ver_stamp.VersionControlStamper

    def __del__(self):
        del self._versions_backend

        for val in self._repos.values():
            shutil.rmtree(val['path'])

    def create_repo(self, repo_name, repo_type):
        path = os.path.join(self.versions_base_dir, repo_name)

        if repo_type == 'mercurial':
            client = hglib.init(dest=path)
            client.close()
        elif repo_type == 'git':
            repo = Repo.init(path=path)
            repo.close()
        else:
            raise RuntimeError('Unknown repository type provided')

        self._repos[repo_name] = {
            'path': path,
            'type': repo_type,
        }

    def write_file(self, repo_name, file_relative_path, content):
        if repo_name not in self._repos:
            raise RuntimeError('repo {0} not found'.format(repo_name))

        path = os.path.join(
            self._repos[repo_name]['path'], file_relative_path
        )
        dir_path = os.path.dirname(path)

        if not os.path.isfile(path):
            pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)

            with open(path, 'w') as f:
                f.write(content)

            if self._repos[repo_name]['type'] == 'mercurial':
                client = hglib.open(self._repos[repo_name]['path'])
                client.add(path.encode())
                client.commit('Added file {0}'.format(path))
                self._repos[repo_name]['changesets'] = {
                    'hash': client.log(branch='default')[0][1].decode('utf-8'),
                    'vcs_type': 'mercurial'
                }
            else:
                client = Repo(self._repos[repo_name]['path'])
                client.index.add([self._repos[repo_name]['path']])
                client.index.commit('Added file {0}'.format(path))
                self._repos[repo_name]['changesets'] = {
                    'hash': client.head.commit.hexsha,
                    'vcs_type': 'git'
                }
        else:
            with open(path, 'w') as f:
                f.write(content)

            if self._repos[repo_name]['type'] == 'mercurial':
                client = hglib.open(self._repos[repo_name]['path'])
                client.commit('Modified file {0}'.format(path))
                self._repos[repo_name]['changesets'] = {
                    'hash': client.log(branch='default')[0][1].decode('utf-8'),
                    'vcs_type': 'mercurial'
                }
            else:
                client = Repo(self._repos[repo_name]['path'])
                client.index.commit('Added file {0}'.format(path))
                self._repos[repo_name]['changesets'] = {
                    'hash': client.head.commit.hexsha,
                    'vcs_type': 'git'
                }

        client.close()

    def get_repo_type(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError('repo {0} not found'.format(repo_name))

        return self._repos[repo_name]['changesets']['vcs_type']

    def get_changesets(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError('repo {0} not found'.format(repo_name))

        return self._repos[repo_name]['changesets']

    def remove_app_version_file(self, app_version_file_path):
        self._versions_backend.remove_app_version_file(app_version_file_path)

    def add_version_info_file(
            self,
            version_info_file_path,
            custom_version=None,
            custom_repos=None):
        if custom_repos is None and custom_version is None:
            return

        with open(version_info_file_path, 'w+') as f:
            if custom_version is not None:
                f.write('version = {0}\n'.format(custom_version))
            if custom_repos is not None:
                f.write('repos = {0}\n'.format(json.dumps(custom_repos)))

        self._versions_backend.add_version_info_file(version_info_file_path)

    def get_be_params(self,
                     app_name,
                     release_mode='debug',
                     starting_version='0.0.0.0',
                     main_system_name=None,
                     version_template='{0}.{1}.{2}'):
        params = {
            'repos_path': self.versions_base_dir,
            'release_mode': release_mode,
            'app_name': app_name,
            'starting_version': starting_version,
            'main_system_name': main_system_name,
            'version_template': version_template,
        }

        if main_system_name is None:
            params['app_version_file'] = '{0}/apps/{1}/version.py'.format(
                self.versions_root_path,
                app_name
            )
        else:
            params['main_version_file'] = '{0}/apps/{1}/main_version.py'.format(
                self.versions_root_path,
                main_system_name
            )
            params['app_version_file'] = '{0}/apps/{1}/{2}/version.py'.format(
                self.versions_root_path,
                main_system_name,
                app_name
            )

        ver_path = stamp_utils.get_versions_repo_path(params['repos_path'])
        params['versions_repo_path'] = ver_path

        return params


class VersionControlBackend(object):
    def __init__(self, remote_versions_root_path, versions_root_path):
        self.remote_versions_root_path = remote_versions_root_path
        self.versions_root_path = versions_root_path

    def __del__(self):
        pass


class MercurialBackend(VersionControlBackend):
    def __init__(self, remote_versions_root_path, versions_root_path):
        VersionControlBackend.__init__(
            self, remote_versions_root_path, versions_root_path
        )

        client = hglib.init(
            dest=self.remote_versions_root_path
        )
        client.close()

        self._mercurial_backend = hglib.clone(
            '{0}'.format(self.remote_versions_root_path),
            '{0}'.format(self.versions_root_path)
        )
        self._mercurial_backend.close()

        with open(os.path.join(versions_root_path, 'init.txt'), 'w+') as f:
            f.write('# init\n')

        self._mercurial_backend = hglib.open(
            '{0}'.format(self.versions_root_path)
        )
        path = os.path.join(versions_root_path, 'init.txt').encode()
        self._mercurial_backend.add(path)
        self._mercurial_backend.commit(
            message='first commit', user='version_manager', include=path
        )
        self._mercurial_backend.push()

    def __del__(self):
        self._mercurial_backend.close()
        VersionControlBackend.__del__(self)

    def remove_app_version_file(self, app_version_file_path):
        client = hglib.open(self.versions_root_path)
        client.remove(app_version_file_path.encode('utf8'))
        client.commit('Manualy removed file {0}'.format(app_version_file_path))
        client.push()
        client.close()

    def add_version_info_file(self, version_info_file_path):
        client = hglib.open(self.versions_root_path)

        client.add(version_info_file_path.encode())
        client.commit(
            message='Manually add version_info file',
            user='version_manager',
            include=version_info_file_path.encode(),
        )

        client.push()
        client.close()


class GitBackend(VersionControlBackend):
    def __init__(self, remote_versions_root_path, versions_root_path):
        VersionControlBackend.__init__(
            self, remote_versions_root_path, versions_root_path
        )

        client = Repo.init(self.remote_versions_root_path, bare=True)
        client.close()

        self._git_backend = Repo.clone_from(
            '{0}'.format(self.remote_versions_root_path),
            '{0}'.format(self.versions_root_path)
        )

        with open(os.path.join(versions_root_path, 'init.txt'), 'w+') as f:
            f.write('# init\n')

        self._git_backend.index.add(
            os.path.join(versions_root_path, 'init.txt')
        )
        self._git_backend.index.commit('first commit')

        self._origin = self._git_backend.remote(name='origin')
        self._origin.push()

    def __del__(self):
        self._git_backend.close()
        VersionControlBackend.__del__(self)

    def remove_app_version_file(self, app_version_file_path):
        client = Repo(self.versions_root_path)
        client.index.remove(app_version_file_path, working_tree=True)
        client.index.commit(
            'Manualy removed file {0}'.format(app_version_file_path)
        )

        origin = client.remote(name='origin')
        origin.push()

        client.close()

    def add_version_info_file(self, version_info_file_path):
        client = Repo(self.versions_root_path)

        client.index.add(version_info_file_path)
        client.index.commit(
            message='Manually add version_info file',
        )

        origin = client.remote(name='origin')
        origin.push()

        client.close()


@pytest.fixture(scope='session')
def session_uuid():
    return uuid.uuid4()


@pytest.fixture(scope='session')
def ver_stamp_env():
    try:
        del os.environ['VER_STAMP_VERSIONS_PATH']
    except:
        pass


def pytest_generate_tests(metafunc):
    if "app_layout" in metafunc.fixturenames:
        metafunc.parametrize("app_layout", ["git", "mercurial"], indirect=True)


@pytest.fixture(scope='function')
def app_layout(request, tmpdir, ver_stamp_env):
    versions = tmpdir.mkdir('versions')
    remote_versions = tmpdir.mkdir('remote_versions')
    app_layout = FSAppLayoutFixture(versions, remote_versions, request.param)

    yield app_layout

    del app_layout
