import pytest
import uuid
import os
import sys
import logging
import pathlib
import shutil
import yaml
from git import Repo

sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))

import stamp_utils
import vmn

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)
TEST_REPO_NAME = "test_repo"
format = "[%(asctime)s.%(msecs)03d] [%(name)s] [%(levelname)s] " "%(message)s"

formatter = logging.Formatter(format, "%Y-%m-%d %H:%M:%S")

cons_handler = logging.StreamHandler(sys.stdout)
cons_handler.setFormatter(formatter)
LOGGER.addHandler(cons_handler)


class FSAppLayoutFixture(object):
    def __init__(self, tmpdir, be_type):
        test_app = tmpdir.mkdir(TEST_REPO_NAME)
        test_app_remote = tmpdir.mkdir("test_repo_remote")
        self.base_dir = test_app.dirname
        self.be_type = be_type
        self.test_app_remote = test_app_remote.strpath
        self.repo_path = test_app.strpath
        self.app_name = "test_app"
        os.environ["VMN_WORKING_DIR"] = self.repo_path

        if be_type == "git":
            self._app_backend = GitBackend(self.test_app_remote, self.repo_path)

        self._repos = {
            TEST_REPO_NAME: {
                "path": test_app.strpath,
                "type": be_type,
                "remote": test_app_remote.strpath,
                "_be": self._app_backend,
            }
        }

    def __del__(self):
        del self._app_backend

        for val in self._repos.values():
            shutil.rmtree(val["path"])

    def create_repo(self, repo_name, repo_type):
        path = os.path.join(self.base_dir, repo_name)

        if repo_type == "git":
            be = GitBackend("{0}_remote".format(path), path)
        else:
            raise RuntimeError("Unknown repository type provided")

        self._repos[repo_name] = {
            "path": path,
            "type": repo_type,
            "remote": "{0}_remote".format(path),
            "_be": be,
        }

        self.write_file_commit_and_push(
            repo_name=repo_name, file_relative_path="a/b/c.txt", content="hello"
        )

        return be

    def merge(self, from_rev, to_rev, squash=False):
        import subprocess

        base_cmd = [
            "git",
            "merge",
        ]
        if squash:
            base_cmd.append("--squash")
        base_cmd.extend([from_rev, to_rev])

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)
        subprocess.call(
            ["git", "commit", "-m", "Merge {} in {}".format(from_rev, to_rev)],
            cwd=self.repo_path,
        )

    def stamp_with_previous_vmn(self):
        import subprocess

        base_cmd = [
            "docker",
            "run",
            "-t",
            f"-u{os.getuid()}:{os.getgid()}",
            "-v",
            f"{self.repo_path}:/test_repo",
            "-v",
            f"{self.base_dir}:{self.base_dir}",
            "previous_vmn_stamper:latest",
            "/stamp_with_previous_vmn.sh",
        ]

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)

    def revert_changes(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))
        if self._repos[repo_name]["type"] != "git":
            raise RuntimeError(
                f"Unsupported repo type: "
                f"{self._repos[repo_name]['type']}"
            )

        client = Repo(self._repos[repo_name]["path"])
        client.git.reset('--hard')
        client.close()

    def write_file_commit_and_push(
            self,
            repo_name,
            file_relative_path,
            content,
            commit=True,
            push=True,
    ):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))
        if self._repos[repo_name]["type"] != "git":
            raise RuntimeError(
                f"Unsupported repo type: "
                f"{self._repos[repo_name]['type']}"
            )

        path = os.path.join(self._repos[repo_name]["path"], file_relative_path)
        dir_path = os.path.dirname(path)
        pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)

        with open(path, "a+") as f:
            f.write(content)

        if not commit:
            return

        client = Repo(self._repos[repo_name]["path"])
        client.index.add([path])
        client.index.commit("Added file {0}".format(path))
        self._repos[repo_name]["changesets"] = {
            "hash": client.head.commit.hexsha,
            "vcs_type": "git",
        }

        if not push:
            return

        client.git.push(
            "--set-upstream",
            "origin",
            "refs/heads/{0}".format(client.active_branch.name),
        )

        client.close()

    def get_repo_type(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))

        return self._repos[repo_name]["changesets"]["vcs_type"]

    def get_changesets(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))

        return self._repos[repo_name]["changesets"]

    def remove_app_version_file(self, app_version_file_path):
        self._app_backend.remove_app_version_file(app_version_file_path)

    def write_conf(self, app_conf_path, template, deps, extra_info):
        with open(app_conf_path, "r+") as f:
            data = yaml.safe_load(f)
            f.seek(0)
            f.write("# Autogenerated by vmn. \n")

            data["conf"] = {
                "template": template,
                "deps": deps,
                "extra_info": extra_info,
            }

            yaml.dump(data, f, sort_keys=False)
            f.truncate()

        self._app_backend.add_conf_file(app_conf_path)


class VersionControlBackend(object):
    def __init__(self, remote_versions_root_path, versions_root_path):
        self.remote_versions_root_path = remote_versions_root_path
        self.root_path = versions_root_path

    def __del__(self):
        pass


class GitBackend(VersionControlBackend):
    def __init__(self, remote_versions_root_path, versions_root_path):
        VersionControlBackend.__init__(
            self, remote_versions_root_path, versions_root_path
        )

        client = Repo.init(self.remote_versions_root_path, bare=True)
        client.close()

        self._git_backend = Repo.clone_from(
            "{0}".format(self.remote_versions_root_path), "{0}".format(self.root_path)
        )

        with open(os.path.join(versions_root_path, "init.txt"), "w+") as f:
            f.write("# init\n")

        self._git_backend.index.add(os.path.join(versions_root_path, "init.txt"))
        self._git_backend.index.commit("first commit")

        self._origin = self._git_backend.remote(name="origin")
        self._origin.push()

        self.be = stamp_utils.GitBackend(versions_root_path)

    def __del__(self):
        self._git_backend.close()
        VersionControlBackend.__del__(self)

    def remove_app_version_file(self, app_version_file_path):
        client = Repo(self.root_path)
        client.index.remove(app_version_file_path, working_tree=True)
        client.index.commit("Manualy removed file {0}".format(app_version_file_path))

        origin = client.remote(name="origin")
        origin.push()

        client.close()

    def add_conf_file(self, conf_path):
        client = Repo(self.root_path)

        client.index.add(conf_path)
        client.index.commit(
            message="Manually add config file",
        )

        origin = client.remote(name="origin")
        origin.push()

        client.close()


@pytest.fixture(scope="session")
def session_uuid():
    return uuid.uuid4()


@pytest.fixture(scope="session")
def ver_stamp_env():
    try:
        del os.environ["VER_STAMP_VERSIONS_PATH"]
    except:
        pass


def pytest_generate_tests(metafunc):
    if "app_layout" in metafunc.fixturenames:
        metafunc.parametrize("app_layout", ["git"], indirect=True)


@pytest.fixture(scope="function")
def app_layout(request, tmpdir, ver_stamp_env):
    app_layout = FSAppLayoutFixture(tmpdir, request.param)

    yield app_layout

    del app_layout
