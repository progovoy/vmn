import pytest
import time
import sys
import os
import importlib.machinery
import types
import pathlib
import copy
import yaml

sys.path.append('{0}/../version_stamp'.format(os.path.dirname(__file__)))
import vmn
from stamp_utils import HostState


def test_basic_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['changesets']) == 1
    vmn.init(params)

    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.1'


def test_multi_repo_dependency(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['changesets']) == 1
    vmn.init(params)

    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    conf = {
        'template': '{0}.{1}.{2}',
        'deps': {'../': {
            'test_repo': {
                'vcs_type': app_layout.be_type,
                'remote': app_layout._app_backend.be.remote(),
            }
        }},
        'extra_info': False
    }
    for repo in (('repo1', 'mercurial'), ('repo2', 'git')):
        be = app_layout.create_repo(
            repo_name=repo[0], repo_type=repo[1]
        )

        conf['deps']['../'].update({
            repo[0]: {
                'vcs_type': repo[1],
                'remote': be.be.remote(),
            }
        })

    app_layout.write_conf(**conf)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.2'
        assert '.' in data['changesets']
        assert '../repo1' in data['changesets']
        assert '../repo2' in data['changesets']


def test_basic_root_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world('root_app/app1', params['working_dir'])
    assert len(params['changesets']) == 1
    vmn.init(params)

    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.1'

    with open(params['root_app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == 1

    app2_params = vmn.build_world('root_app/app2', params['working_dir'])
    assert len(app2_params['changesets']) == 1

    app2_params['release_mode'] = 'minor'
    app2_params['starting_version'] = '0.0.0.0'
    vmn.stamp(app2_params)

    with open(app2_params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.1.0'

    with open(app2_params['root_app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == 2


def test_starting_version(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['changesets']) == 1
    vmn.init(params)

    params['release_mode'] = 'minor'
    params['starting_version'] = '1.2.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '1.3.0'


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
