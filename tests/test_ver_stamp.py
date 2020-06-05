import pytest
import sys
import os
import copy
import yaml

sys.path.append('{0}/../version_stamp'.format(os.path.dirname(__file__)))
import vmn
from stamp_utils import HostState


def test_basic_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['user_repos_details']) == 1
    vmn.init(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.1'

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.1'


def test_multi_repo_dependency(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['user_repos_details']) == 1
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

    with open(params['app_conf_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert '../' in data['conf']['deps']
        assert 'test_repo' in data['conf']['deps']['../']
        assert 'repo1' in data['conf']['deps']['../']
        assert 'repo2' in data['conf']['deps']['../']


def test_basic_root_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world('root_app/app1', params['working_dir'])
    assert len(params['user_repos_details']) == 1
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
    assert len(app2_params['user_repos_details']) == 1

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
    assert len(params['user_repos_details']) == 1
    vmn.init(params)

    params['release_mode'] = 'minor'
    params['starting_version'] = '1.2.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '1.3.0'


def test_version_template(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)

    params['release_mode'] = 'minor'
    params['starting_version'] = '1.2.0.0'
    vmn.stamp(params)

    configured_template = None
    with open(params['app_conf_path'], 'r') as f:
        data = yaml.safe_load(f)
        configured_template = data['conf']['template']

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        _, octats = vmn.IVersionsStamper.parse_template(configured_template)
        formated_version = vmn.IVersionsStamper.get_formatted_version(
            '1.3.0.0',
            configured_template,
            octats
        )
        assert data['version'] == formated_version

    template = 'ap{0}xx{0}XX{1}AC@{0}{2}{3}C'
    _, octats = vmn.IVersionsStamper.parse_template(template)
    formated_version = vmn.IVersionsStamper.get_formatted_version(
        '2.0.9.6',
        template,
        octats
    )
    assert formated_version == 'ap2xx2XX0AC@296C'


@pytest.mark.skip(reason="broken mercurial")
def test_basic_goto(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['user_repos_details']) == 1
    vmn.init(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.1'

    app_layout.write_file('test_repo', 'a.yxy', 'msg')

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params)

    with open(params['app_path'], 'r') as f:
        data = yaml.safe_load(f)
        assert data['version'] == '0.0.2'

    c1 = app_layout._app_backend.be.changeset()
    assert vmn.goto_version(params, '1.0.1.0') == 1
    assert vmn.goto_version(params, '0.0.1.0') == 0
    c2 = app_layout._app_backend.be.changeset()
    assert c1 != c2
    assert vmn.goto_version(params, '0.0.2.0') == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    assert vmn.goto_version(params, None) == 0
    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4
