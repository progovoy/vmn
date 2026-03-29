#!/usr/bin/env python3
"""Git backend mixin: branch, checkout, and state-check operations."""
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator


class GitBranchMixin:
    """Methods for branch management and state checks. Mixed into GitBackend."""

    def in_detached_head(self):
        return self._be.head.is_detached

    @measure_runtime_decorator
    def get_active_branch(self):
        # TODO:: return the full ref name: refs/heads/..
        if not self.in_detached_head():
            active_branch = self._be.active_branch.name
        else:
            active_branch = self.get_branch_from_changeset(self._be.head.commit.hexsha)

        return active_branch

    @measure_runtime_decorator
    def get_branch_from_changeset(self, hexsha):
        out = self._be.git.branch("--contains", hexsha)

        branches = out.splitlines()

        # Clean up each branch name by stripping whitespace and the '*' character
        active_branches = []
        for branch in branches:
            cleaned_branch = branch.strip().lstrip("*").strip()
            if "HEAD detached" not in cleaned_branch:
                active_branches.append(cleaned_branch)

        if len(active_branches) > 1:
            VMN_LOGGER.info(
                f"{self._be.head.commit.hexsha} is "
                f"related to multiple branches: {active_branches}. "
                "Using the first one as the active branch"
            )

        if not active_branches:
            out = self._be.git.branch("-r", "--contains", hexsha)
            # Filter out symbolic refs (e.g., "origin/HEAD -> origin/main")
            remote_branches = [
                stripped for b in out.split("\n")
                if (stripped := b.strip()) and "->" not in stripped
            ]
            out = remote_branches[0] if remote_branches else None

            if not out:
                raise RuntimeError(f"Failed to find remote branch for hex: {hexsha}")

            assert out.startswith(self.selected_remote.name)

            local_branch_name = (
                f"vmn_tracking_remote__{out.replace('/', '_')}__from_{hexsha[:5]}"
            )
            self._be.git.branch(local_branch_name, out)
            self._be.git.branch(f"--set-upstream-to={out}", local_branch_name)

            VMN_LOGGER.debug(
                f"Setting local branch {local_branch_name} "
                f"to track remote branch {out}"
            )

            self.active_branch = local_branch_name
            self.remote_active_branch = out

            remote_branch_hexsha = self._be.refs[out].commit.hexsha
            if remote_branch_hexsha == hexsha:
                ret = self.checkout_branch()
                assert ret is not None

            active_branches.append(local_branch_name)

        active_branch = active_branches[0]

        return active_branch

    @measure_runtime_decorator
    def checkout(self, rev=None, tag=None, branch=None):
        if tag is not None:
            rev = f"refs/tags/{tag}"
        elif branch is not None:
            # TODO:: f"refs/heads/{branch}"
            rev = f"{branch}"

        assert rev is not None

        self._be.git.checkout(rev)

        self.detached_head = self.in_detached_head()

    @measure_runtime_decorator
    def checkout_branch(self, branch_name=None):
        try:
            if branch_name is None:
                branch_name = self.active_branch

            self.checkout(branch=branch_name)
        except Exception:
            VMN_LOGGER.error("Failed to get branch name")
            VMN_LOGGER.debug("Exception info: ", exc_info=True)

            return None

        return self._be.active_branch.commit.hexsha

    @measure_runtime_decorator
    def get_remote_tracking_branch(self, local_branch_name):
        command = [
            "git",
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{local_branch_name}@{{u}}",
        ]

        try:
            ret = self._be.git.execute(command)

            try:
                assert ret.startswith(self.selected_remote.name)
            except Exception:
                VMN_LOGGER.warning(
                    f"Found remote branch {ret} however it belongs to a "
                    f"different remote that vmn has selected to work with. "
                    f"Will behave like no remote was found. The remote that vmn has "
                    f"selected to work with is: {self.selected_remote.name}"
                )

                return None

            return ret
        except Exception:
            return None

    @measure_runtime_decorator
    def prepare_for_remote_operation(self):
        if self.remote_active_branch is not None:
            return 0

        local_branch_name = self.active_branch

        VMN_LOGGER.warning(
            f"No remote branch for local branch: {local_branch_name} "
            f"was found for repo {self.repo_path}. Will try to set upstream for it"
        )

        assumed_remote = f"{self.selected_remote.name}/{local_branch_name}"

        out = self._be.git.branch("-r", "--contains", "HEAD")
        # Filter out symbolic refs (e.g., "origin/HEAD -> origin/main")
        out = [s.strip() for s in out.split("\n") if s.strip() and "->" not in s]

        VMN_LOGGER.info(f"The output of 'git branch -r --contains HEAD' is:\n{out}")

        if assumed_remote in out:
            VMN_LOGGER.info(
                f"Assuming remote: {assumed_remote} as it was present in the output"
            )
            out = assumed_remote
        elif out:
            VMN_LOGGER.info(
                f"Assuming remote: {out[0]} as this is the first element in the output"
            )
            out = out[0]

        if not out:
            VMN_LOGGER.info(
                f"Assuming remote: {assumed_remote} as the output was empty"
            )
            out = assumed_remote

        try:
            self._be.git.execute(
                [
                    "git",
                    "remote",
                    "set-branches",
                    "--add",
                    self.selected_remote.name,
                    local_branch_name,
                ]
            )
            self._be.git.branch(f"--set-upstream-to={out}", local_branch_name)
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to set upstream branch for {local_branch_name}:", exc_info=True
            )
            return 1

        self.remote_active_branch = out

        return 0

    @measure_runtime_decorator
    def check_for_pending_changes(self):
        if self._be.is_dirty():
            err = f"Pending changes in {self.root()}."
            return err

        return None

    @measure_runtime_decorator
    def check_for_outgoing_changes(self):
        if self.in_detached_head():
            err = f"Detached head in {self.root()}."
            return err

        if self.remote_active_branch is None:
            err = (
                f"No upstream branch found in {self.root()}. "
                f"for local branch {self.active_branch}. "
                f"Probably no upstream branch is set"
            )

            return err

        branch_name = self.active_branch
        try:
            self._be.git.rev_parse("--verify", f"{self.remote_active_branch}")
        except Exception:
            err = (
                f"Remote branch {self.remote_active_branch} does not exist. "
                "Please set-upstream branch to "
                f"{self.remote_active_branch} of branch {branch_name}"
            )
            return err

        outgoing = tuple(
            self._be.iter_commits(
                f"{self.remote_active_branch}..{branch_name}", max_count=1
            )
        )

        if outgoing:
            err = (
                f"Outgoing changes in {self.root()} "
                f"from branch {branch_name} "
                f"({self.remote_active_branch}..{branch_name})"
            )

            return err

        return None
