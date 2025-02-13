import logging
import os
import pathlib
import re
import shutil
import stat
import sys
import uuid

import git
import pytest
import yaml
from git import Repo

sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))

import stamp_utils
import subprocess

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
        test_app_remote = tmpdir.joinpath(f"{TEST_REPO_NAME}_remote")
        test_app_remote.mkdir(exist_ok=True)
        self.base_dir = str(tmpdir.absolute())
        self.be_type = be_type
        self.test_app_remote = str(test_app_remote.absolute())
        self.repo_path = os.path.join(self.base_dir, f"{TEST_REPO_NAME}_0")
        self.app_name = "test_app"

        if be_type == "git":
            self._app_backend = GitBackend(self.test_app_remote, self.repo_path)

        self.set_working_dir(self.repo_path)

        root_path = stamp_utils.resolve_root_path()
        vmn_path = os.path.join(root_path, ".vmn")
        pathlib.Path(vmn_path).mkdir(parents=True, exist_ok=True)

        self._repos = {
            f"{TEST_REPO_NAME}_0": {
                "path": self.repo_path,
                "type": be_type,
                "remote": self.test_app_remote,
                "_be": self._app_backend,
                "clones_paths": [self.repo_path],
            }
        }

    def __del__(self):
        del self._app_backend

    def set_working_dir(self, repo_path):
        os.environ["VMN_WORKING_DIR"] = repo_path

    def create_repo(self, repo_name, repo_type):
        path = os.path.join(self.base_dir, f"{repo_name}")
        remote_path = f"{path}_remote"

        if repo_type == "git":
            be = GitBackend(remote_path, path)
        else:
            raise RuntimeError("Unknown repository type provided")

        self._repos[repo_name] = {
            "path": path,
            "type": repo_type,
            "remote": remote_path,
            "_be": be,
            "clones_paths": [path],
        }

        self.write_file_commit_and_push(
            repo_name=repo_name, file_relative_path="a/b/c.txt", content="hello"
        )

        return be

    def create_new_clone(self, repo_name, depth=0):
        base_cmd = ["git", "clone"]
        if depth:
            base_cmd.append(f"--depth={depth}")

        base_cmd.append(f"file://{self._repos[repo_name]['remote']}")

        suffix_len = len("remote")
        local_path = f"{self._repos[repo_name]['remote'][:-suffix_len]}{len(self._repos[repo_name]['clones_paths'])}"
        self._repos[repo_name]["clones_paths"].append(local_path)

        base_cmd.append(local_path)

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.base_dir)

        return local_path

    def merge(self, from_rev, to_rev, squash=False, no_ff=False, delete_source=False):
        base_cmd = ["git", "merge"]
        if squash:
            base_cmd.append("--squash")
        if no_ff:
            base_cmd.append("--no-ff")

        base_cmd.extend([from_rev, to_rev])

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)
        subprocess.call(
            ["git", "commit", "-m", "Merge {} in {}".format(from_rev, to_rev)],
            cwd=self.repo_path,
        )

        subprocess.call(["git", "branch", "-D", from_rev], cwd=self.repo_path)

        subprocess.call(["git", "push"], cwd=self.repo_path)

    def git_cmd(self, repo_name=f"{TEST_REPO_NAME}_0", args=()):
        base_cmd = ["git"]
        base_cmd.extend(args)

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        ret = subprocess.check_output(
            base_cmd, cwd=self._repos[repo_name]["_be"].root_path
        )

        return ret.decode("utf-8")

    def rebase(self, target, who_to_put_on_target, no_ff=False):

        base_cmd = ["git", "rebase", target, who_to_put_on_target]
        if no_ff:
            base_cmd.append("--no-ff")

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)

    def checkout(
        self,
        target,
        repo_name=f"{TEST_REPO_NAME}_0",
        branch_to_track=None,
        create_new=False,
    ):
        base_cmd = ["git", "checkout"]
        if create_new:
            base_cmd.append("-b")

        base_cmd.append(target)

        if branch_to_track:
            base_cmd.append(branch_to_track)

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))

        subprocess.call(base_cmd, cwd=self._repos[repo_name]["_be"].root_path)

    def checkout_jekins(
        self,
        target,
        repo_name=f"{TEST_REPO_NAME}_0",
        branch_to_track=None,
        create_new=False,
    ):
        base_cmd = [
            "git",
            "fetch",
            "--tags",
            "--force",
            "--",
            self._repos[repo_name]["_be"].selected_remote.url,
            "+refs/heads/*:refs/remotes/origin/*",
        ]
        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))

        p = self._repos[repo_name]["_be"].root_path
        subprocess.call(base_cmd, cwd=p)

        base_cmd = ["git", "rev-parse", f"origin/{target}"]
        sha = subprocess.check_output(base_cmd, cwd=p)
        # decode output from bytes to string
        sha = sha.decode("utf-8").strip()

        base_cmd = ["git", "rev-parse", f"origin/{target}"]
        subprocess.call(base_cmd, cwd=p)

        base_cmd = ["git", "config", "core.sparsecheckout"]
        subprocess.call(base_cmd, cwd=p)

        base_cmd = ["git", "checkout", "-f", sha]
        subprocess.call(base_cmd, cwd=p)

        base_cmd = ["git", "branch", "-D", target]
        subprocess.call(base_cmd, cwd=p)

        base_cmd = ["git", "checkout", "-b", target, sha]
        subprocess.call(base_cmd, cwd=p)

    def delete_branch(
        self,
        branch_name,
        repo_name=f"{TEST_REPO_NAME}_0",
    ):
        base_cmd = ["git", "branch", "-D", branch_name]
        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))

        subprocess.call(base_cmd, cwd=self._repos[repo_name]["_be"].root_path)

    def push(self, force_lease=False):
        base_cmd = ["git", "push"]

        if force_lease:
            base_cmd.append("--force-with-lease")

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)

    def pull(self, tags=False):
        base_cmd = ["git", "pull"]

        if tags:
            base_cmd.append("--tags")

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)

    def get_all_tags(self):
        cmd = ["--sort", "taggerdate"]
        tags = self._app_backend._git_backend.git.tag(*cmd).split("\n")

        tags = tags[::-1]
        if len(tags) == 1 and tags[0] == "":
            tags.pop(0)

        return tags

    def create_tag(self, commit_hash, tag_name):
        base_cmd = ["git", "tag", tag_name, commit_hash]

        LOGGER.info(f"going to run: {' '.join(base_cmd)}")
        subprocess.call(base_cmd, cwd=self.repo_path)

        base_cmd = ["git", "push", "--tags"]

        LOGGER.info(f"going to run: {' '.join(base_cmd)}")
        subprocess.call(base_cmd, cwd=self.repo_path)

    def is_file_tracked(self, file_path):
        try:
            self._app_backend._be.git.execute(
                ["git", "ls-files", "--error-unmatch", f"{file_path}"]
            )
        except git.GitCommandError:
            return False

        return True

    def remove_tag(self, tag_name):
        base_cmd = ["git", "tag", "-d", tag_name]

        LOGGER.info(f"going to run: {' '.join(base_cmd)}")
        subprocess.call(base_cmd, cwd=self.repo_path)

        base_cmd = [
            "git",
            "push",
            "--delete",
            self._app_backend.be.selected_remote.name,
            tag_name,
        ]

        LOGGER.info(f"going to run: {' '.join(base_cmd)}")
        subprocess.call(base_cmd, cwd=self.repo_path)

    def stamp_with_previous_vmn(self, vmn_version):
        dir_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "retro_versions_checks")
        previous_stamper_dir = os.path.join(dir_path, "build_previous_vmn_stamper.sh")

        if not os.path.exists(previous_stamper_dir):
            LOGGER.info("No previous VMN stamper found")
            return

        if not os.access(previous_stamper_dir, os.X_OK):
            raise RuntimeError(
                f"Please run: chmod +x -R {dir_path}\n"
                f"If running on Windows, please run in addition dos2unix for every file in the {dir_path} directory"
            )

        base_cmd = [
            previous_stamper_dir,
            vmn_version,
        ]

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd)

        base_cmd = [
            "docker",
            "run",
            "--init",
            "-t",
            f"-u{os.getuid()}:{os.getgid()}",
            "-v",
            f"{self.repo_path}:/test_repo_0",
            "-v",
            f"{self.base_dir}:{self.base_dir}",
            f"previous_vmn_stamper:{vmn_version}",
            f"/stamp_with_{vmn_version}_vmn.sh",
        ]

        LOGGER.info("going to run: {}".format(" ".join(base_cmd)))
        subprocess.call(base_cmd, cwd=self.repo_path)
        pass

    def revert_changes(self, repo_name):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))
        if self._repos[repo_name]["type"] != "git":
            raise RuntimeError(
                f"Unsupported repo type: " f"{self._repos[repo_name]['type']}"
            )

        client = Repo(self._repos[repo_name]["path"])
        client.git.reset("--hard")
        client.close()

    def write_file_commit_and_push(
        self,
        repo_name,
        file_relative_path,
        content,
        commit=True,
        push=True,
        add_exec=False,
        commit_msg=None,
    ):
        if repo_name not in self._repos:
            raise RuntimeError("repo {0} not found".format(repo_name))
        if self._repos[repo_name]["type"] != "git":
            raise RuntimeError(
                f"Unsupported repo type: " f"{self._repos[repo_name]['type']}"
            )

        path = os.path.join(self._repos[repo_name]["path"], file_relative_path)
        dir_path = os.path.dirname(path)
        pathlib.Path(dir_path).mkdir(parents=True, exist_ok=True)

        with open(path, "a+") as f:
            f.write(content)

        if add_exec:
            st = os.stat(path)
            os.chmod(path, st.st_mode | stat.S_IEXEC)

        if not commit:
            return

        client = Repo(self._repos[repo_name]["path"])
        client.index.add([path])
        if commit_msg is None:
            commit_msg = f"Added file {path}"

        client.index.commit(commit_msg)
        self._repos[repo_name]["changesets"] = {
            "hash": client.head.commit.hexsha,
            "vcs_type": "git",
        }

        if not push:
            return

        client.git.push(
            "--set-upstream",
            client.remotes[0].name,
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

    def remove_file(self, file_path, from_git=True):
        os.remove(file_path)

        if from_git:
            self._app_backend.remove_file(file_path)

    def write_conf(
        self,
        app_conf_path,
        template=None,
        deps=None,
        extra_info=None,
        version_backends=None,
        create_verinfo_files=None,
        policies=None,
        conventional_commits=None,
    ):
        with open(app_conf_path, "w") as f:
            f.write("# Autogenerated by vmn. \n")

            data = {"conf": {}}

            if template is not None:
                data["conf"]["template"] = template
            if deps is not None:
                data["conf"]["deps"] = deps
            if extra_info is not None:
                data["conf"]["extra_info"] = extra_info
            if version_backends is not None:
                data["conf"]["version_backends"] = version_backends
            if create_verinfo_files is not None:
                data["conf"]["create_verinfo_files"] = create_verinfo_files
            if policies is not None:
                data["conf"]["policies"] = policies
            if conventional_commits is not None:
                data["conf"]["conventional_commits"] = conventional_commits

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

        try:
            self._git_backend = Repo.clone_from(
                "{0}".format(self.remote_versions_root_path),
                "{0}".format(self.root_path),
                # depth=1,
            )
        except Exception as exc:

            if hasattr(exc, "stderr") and "exist" not in exc.stderr:
                raise exc

            self._git_backend = git.Repo(self.root_path)

        p = os.path.join(versions_root_path, "init.txt")
        if not os.path.exists(p):
            with open(p, "w+") as f:
                f.write("# init\n")

            self._git_backend.index.add(os.path.join(versions_root_path, "init.txt"))
            self._git_backend.index.commit("first commit")

            self.selected_remote = self._git_backend.remotes[0]
            self.selected_remote.push()

        self.be = stamp_utils.GitBackend(versions_root_path)

    def __del__(self):
        self._git_backend.close()
        VersionControlBackend.__del__(self)

    def remove_file(self, file_path):
        client = Repo(self.root_path)
        client.index.remove(file_path, working_tree=True)
        client.index.commit("Manualy removed file {0}".format(file_path))

        origin = client.remotes[0]
        origin.push()

        client.close()

    def add_conf_file(self, conf_path):
        client = Repo(self.root_path)

        client.index.add(conf_path)
        client.index.commit(message="Manually add config file")

        origin = client.remotes[0]
        origin.push()

        client.close()


@pytest.fixture(scope="session")
def session_uuid():
    return uuid.uuid4()


def pytest_generate_tests(metafunc):
    if "app_layout" in metafunc.fixturenames:
        metafunc.parametrize("app_layout", ["git"], indirect=True)


@pytest.fixture(scope="function")
def app_layout(request, tmpdir):
    from pathlib import Path

    tmpdir = Path(tmpdir)
    if "VMN_TESTS_CUSTOM_DIR" in os.environ:
        tmpdir = Path(os.environ["VMN_TESTS_CUSTOM_DIR"])

    app_layout = FSAppLayoutFixture(tmpdir, request.param)

    yield app_layout

    del app_layout

    if "VMN_TESTS_CUSTOM_DIR" not in os.environ:
        shutil.rmtree(str(tmpdir.absolute()))
