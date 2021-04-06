import sys
import os
import copy
import yaml
import shutil

sys.path.append('{0}/../version_stamp'.format(os.path.dirname(__file__)))

import vmn
import stamp_utils

vmn.LOGGER = stamp_utils.init_stamp_logger(True)


def test_basic_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'

    old_name = params['name']
    params['name'] = '{0}_{1}'.format(params['name'], '2')
    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params, init_only=True)
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(
        app_name=params['name']
    )
    data = ver_info['stamping']['app']
    assert data['version'] == '1.0.1'

    params['name'] = old_name
    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(
        app_name=params['name']
    )
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'


def test_basic_show(app_layout, capfd):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    out, err = capfd.readouterr()
    assert not out

    params['verbose'] = False
    params['raw'] = False
    vmn.show(params)
    out, err = capfd.readouterr()
    assert '0.0.1\n' == out

    params['verbose'] = False
    params['raw'] = True
    vmn.show(params)
    out, err = capfd.readouterr()
    assert '0.0.1.0\n' == out

    params['verbose'] = True
    vmn.show(params)
    out, err = capfd.readouterr()
    try:
        data = yaml.safe_load(out)
    except Exception as we:
        assert False


def test_multi_repo_dependency(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
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
    for repo in (('repo1', 'git'), ('repo2', 'git')):
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

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.2'

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


def test_goto_deleted_repos(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
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
    for repo in (('repo1', 'git'), ('repo2', 'git')):
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

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']

    dir_path = app_layout._repos['repo2']['path']
    shutil.rmtree(dir_path)  # deleting repo_b
    assert vmn.goto_version(params, '0.0.2.0') == 0


def test_basic_root_stamp(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world('root_app/app1', params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)

    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'

    data = ver_info['stamping']['root_app']
    assert data['version'] == 1

    app2_params = vmn.build_world('root_app/app2', params['working_dir'])
    assert len(app2_params['actual_deps_state']) == 1

    app2_params['release_mode'] = 'minor'
    app2_params['starting_version'] = '0.0.0.0'
    vmn.stamp(app2_params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(
        app_name=app2_params['name']
    )
    data = ver_info['stamping']['app']
    assert data['version'] == '0.1.0'
    data = ver_info['stamping']['root_app']
    assert data['version'] == 2


def test_starting_version(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)

    params['release_mode'] = 'minor'
    params['starting_version'] = '1.2.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
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

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '1.3.0'
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


def test_basic_goto(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'

    app_layout.write_file_commit_and_push('test_repo', 'a.yxy', 'msg')

    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '1.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
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


def test_stamp_on_branch_merge_squash(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    assert len(params['actual_deps_state']) == 1
    vmn.init(params)
    params = vmn.build_world(params['name'], params['working_dir'])
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    app_layout._app_backend.be.checkout(('-b', 'new_branch'))
    app_layout.write_file_commit_and_push('test_repo', 'f1.file', 'msg1')
    app_layout._app_backend._origin.pull(rebase=True)
    vmn.stamp(params)  # first stamp 0.0.1
    app_layout.write_file_commit_and_push('test_repo', 'f2.file', 'msg2')
    app_layout._app_backend._origin.pull(rebase=True)
    vmn.stamp(params)  # 0.0.2
    app_layout.write_file_commit_and_push('test_repo', 'f3.file', 'msg3')
    app_layout._app_backend._origin.pull(rebase=True)
    vmn.stamp(params)  # 0.0.3
    app_layout._app_backend.be.checkout('master')
    app_layout.merge(from_rev='new_branch', to_rev='master', squash=True)
    app_layout._app_backend._origin.pull(rebase=True)

    app_layout._app_backend.be.push()
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']

    assert data['version'] == '0.0.4'


def test_get_version(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    app_layout._app_backend.be.checkout(('-b', 'new_branch'))
    app_layout.write_file_commit_and_push('test_repo', 'f1.file', 'msg1')
    app_layout._app_backend._origin.pull(rebase=True)
    vmn.stamp(params)  # first stamp 0.0.1
    app_layout._app_backend.be.checkout('master')
    app_layout.merge(from_rev='new_branch', to_rev='master', squash=True)
    app_layout._app_backend._origin.pull(rebase=True)
    app_layout._app_backend.be.push()
    vmn.stamp(params)
    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.2'


def test_get_version_number_from_file(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.2.0.0'
    vmn.stamp(params)  # just to create the relative folder tree, I.E: .vmn/app_name/last_known_app_version.yml
    ver_stamper = vmn.VersionControlStamper(params)
    assert ver_stamper.get_version_number_from_file() == '0.2.1.0'


def test_read_version_from_file(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.1.0.0'
    vmn.stamp(params)
    file_path = '{}/{}'.format(params.get('app_dir_path'), vmn.VER_FILE_NAME)
    app_layout.write_file_commit_and_push('test_repo', 'f1.file', 'msg1')
    app_layout._app_backend._origin.pull(rebase=True)
    vmn.stamp(params)
    with open(file_path, 'r') as fid:
        ver_dict = yaml.load(fid)
    assert '0.1.2.0' == ver_dict.get('last_stamped_version')


def test_system_backward_comp_file_vs_commit(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.1.0.0'
    vmn.stamp(params)
    file_path = '{}/{}'.format(params.get('app_dir_path'), vmn.VER_FILE_NAME)
    app_layout.remove_app_version_file(file_path)
    # in this point we simulate the case were using an old vmn that searches for version numbers in commit message,
    # but stamping with the new method (write and read from file)
    vmn.stamp(params)
    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    _version = ver_info['stamping']['app']['_version']
    assert '0.1.2.0' == _version
    with open(file_path, 'r') as fid:
        ver_dict = yaml.load(fid)
    assert '0.1.2.0' == ver_dict.get('last_stamped_version')


def test_manual_file_adjustment(app_layout):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world(params['name'], params['working_dir'])
    vmn.init(params)
    params['release_mode'] = 'patch'
    params['starting_version'] = '0.1.0.0'
    vmn.stamp(params)
    file_path = '{}/{}'.format(params.get('app_dir_path'), vmn.VER_FILE_NAME)
    app_layout.remove_app_version_file(file_path)
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push('test_repo',
                                          '.vmn/test_app/{}'.format(vmn.VER_FILE_NAME),
                                          'last_stamped_version: 0.2.3.0')
    vmn.stamp(params)
    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    _version = ver_info['stamping']['app']['_version']
    assert '0.2.4.0' == _version


def test_basic_root_show(app_layout,capfd):
    params = copy.deepcopy(app_layout.params)
    params = vmn.build_world('root_app/app1', params['working_dir'])
    vmn.init(params)

    params['release_mode'] = 'patch'
    params['starting_version'] = '0.0.0.0'
    vmn.stamp(params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(app_name=params['name'])
    data = ver_info['stamping']['app']
    assert data['version'] == '0.0.1'

    data = ver_info['stamping']['root_app']
    assert data['version'] == 1

    app2_params = vmn.build_world('root_app/app2', params['working_dir'])

    app2_params['release_mode'] = 'minor'
    app2_params['starting_version'] = '0.0.0.0'
    vmn.stamp(app2_params)

    ver_info = app_layout._app_backend.be.get_vmn_version_info(
        app_name=app2_params['name']
    )
    data = ver_info['stamping']['app']
    data = ver_info['stamping']['root_app']
    params['root'] = True
    vmn.show(params)
    out, err = capfd.readouterr()
    assert '2\n' == out