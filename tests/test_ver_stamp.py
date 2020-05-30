import pytest
import time
import sys
import os
import importlib.machinery
import types
import pathlib
import copy

sys.path.append('{0}/../version_stamp'.format(os.path.dirname(__file__)))
import vmn
from stamp_utils import HostState


def test_get_current_changesets(app_layout):
    params = copy.deepcopy(app_layout.params)
    vmn.init(params)
    vmn.build_world(params)
    params['release_mode'] = 'patch'
    vmn.stamp(params)
    vmn.build_world(params)

    assert len(changesets) == 1

    current_changesets = {}
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

        current_changesets[repo[0]] = \
            app_layout.get_changesets(repo_name=repo[0])

        current_changesets[repo[0]] = \
            app_layout.get_changesets(repo_name=repo[0])

    params = copy.deepcopy(app_layout.params)
    vmn.init(params)
    vmn.stamp(params)

    vmn.build_world(params)
    changesets = params['changesets']

    for k,v in changesets.items():
        assert k in current_changesets
        assert current_changesets[k]['hash'] == v['hash']
        assert current_changesets[k]['vcs_type'] == v['vcs_type']


def test_stamp_version(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params(
        'test_app1', 'patch')

    be = vmn.VersionControlStamper(params)
    be.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    current_version = be.stamp_app_version(changesets)
    assert current_version == '0.0.1.0'


def test_stamp_main_version(app_layout):
    strings = time.strftime("%y,%m")
    strings = strings.split(',')
    tmp_date_ver = '{0}.{1}'.format(strings[0], strings[1])

    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params(
        app_name='test_app1',
        release_mode='patch',
        root_app_name='MainSystem'
    )

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    current_version = mbe.stamp_app_version(changesets)

    assert current_version == '0.0.1.0'

    formatted_main_ver = mbe.stamp_main_system_version(
        current_version
    )

    assert formatted_main_ver == '{0}.1'.format(tmp_date_ver)

    mbe.publish(current_version, formatted_main_ver)
    mbe.deallocate_backend()

    app_layout.write_file(
        repo_name='repo1', file_relative_path='a/b/c.txt', content='hello3'
    )

    params = app_layout.get_be_params(
        app_name='test_app2',
        release_mode='patch',
        root_app_name='MainSystem'
    )

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    current_version = mbe.stamp_app_version(changesets)

    assert current_version == '0.0.1.0'

    formatted_main_ver = mbe.stamp_main_system_version(
        current_version
    )

    assert formatted_main_ver == '{0}.2'.format(tmp_date_ver)

    mbe.publish(current_version, formatted_main_ver)
    mbe.deallocate_backend()

    params = app_layout.get_be_params(
        app_name='test_app1',
        release_mode='patch',
        root_app_name='MainSystem'
    )

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    current_version = mbe.stamp_app_version(changesets)

    assert current_version == '0.0.2.0'

    formatted_main_ver = mbe.stamp_main_system_version(
        current_version
    )

    assert formatted_main_ver == '{0}.3'.format(tmp_date_ver)

    mbe.publish(current_version, formatted_main_ver)
    mbe.deallocate_backend()


def test_starting_version(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params('test_app1', 'patch', '1.9.5.0')

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    assert mbe._starting_version == '1.9.5.0'

    ver = mbe.find_version(changesets)
    assert ver is None

    current_version = mbe.stamp_app_version(changesets)

    assert current_version == '1.9.6.0'


def test_find_version(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params(
        'test_app1', 'patch')
    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    ver = mbe.find_version(changesets)
    assert ver is None

    current_version = mbe.stamp_app_version(changesets)
    assert current_version == '0.0.1.0'

    mbe.publish(current_version)
    mbe.deallocate_backend()

    release_modes = ('patch', 'minor', 'major', 'micro')
    for release_mode in release_modes:
        params = app_layout.get_be_params(
            'test_app1', release_mode)
        mbe = vmn.VersionControlStamper(params)
        mbe.allocate_backend()
        changesets = HostState.get_current_changeset(
            app_layout.base_dir
        )

        ver = mbe.find_version(changesets)
        assert ver == '0.0.1.0'

        mbe.deallocate_backend()

    # Add a change
    app_layout.write_file(
        repo_name='repo1', file_relative_path='a/b/c.txt', content='xxx'
    )

    params = app_layout.get_be_params(
        'test_app1', 'patch')
    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    ver = mbe.find_version(changesets)
    assert ver is None

    current_version = mbe.stamp_app_version(changesets)
    assert current_version == '0.0.2.0'


def test_output(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt',
            content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt',
            content='hello2'
        )

    params = app_layout.get_be_params(
        'test_app1', 'patch')
    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    output = vmn.get_version(mbe, changesets)
    assert output == '0.0.1'

    output = vmn.get_version(mbe, changesets)
    assert output == '0.0.1'


@pytest.mark.skip(reason="Probably thi feature is no longer needed")
def test_find_recurring_version(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params('test_app1', 'patch')
    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    assert mbe._starting_version == '0.0.0.0'

    current_version = mbe.stamp_app_version(changesets)
    mbe.publish(current_version)
    mbe.deallocate_backend()

    app_layout.remove_app_version_file(params['app_version_file'])

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    ver = mbe.find_version(changesets)
    assert ver is None
    assert mbe._starting_version == '0.0.1.0'

    current_version = mbe.stamp_app_version(changesets)
    assert current_version == '0.0.2.0'


def test_version_info(app_layout):
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello'
        )
        app_layout.write_file(
            repo_name=repo[0], file_relative_path='a/b/c.txt', content='hello2'
        )

    params = app_layout.get_be_params(
        'test_app1', 'patch')
    dir_path = os.path.dirname(params['app_version_file'])
    pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)
    app_layout.write_conf(
        '{0}/version_info.py'.format(dir_path),
        custom_repos=('repo2',)
    )

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    current_version = mbe.stamp_app_version(changesets)
    loader = importlib.machinery.SourceFileLoader(
        'version', params['app_version_file'])
    ver = types.ModuleType(loader.name)
    loader.exec_module(ver)

    repo_changeset = None
    for k,v in changesets.items():
        if k != 'repo2':
            continue

        repo_changeset = v['hash']
        break

    assert 'repo2' in ver.changesets
    assert len(ver.changesets.keys()) == 1
    assert ver.changesets['repo2']['hash'] == repo_changeset
    assert ver._version == current_version

    mbe.publish(current_version)

    app_layout.write_file(
        repo_name='repo1', file_relative_path='a/b/D.txt', content='hello'
    )

    changesets = HostState.get_current_changeset(
        app_layout.base_dir
    )

    found_version = mbe.find_version(changesets)
    assert found_version == current_version

    found_version = mbe.find_version({})
    assert found_version == None

    mbe.deallocate_backend()


def test_version_template(app_layout):
    params = app_layout.get_be_params(
        'test_app1', 'patch')

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    ver = mbe.get_be_formatted_version('1.0.3.6')
    assert ver == '1.0.3'

    params = app_layout.get_be_params(
        'test_app1', 'patch', version_template='ap{0}xx{0}XX{1}AC@{0}{2}{3}C')

    mbe = vmn.VersionControlStamper(params)
    mbe.allocate_backend()
    ver = mbe.get_be_formatted_version('1.0.3.6')
    assert ver == 'ap1xxXX0AC@36C'
