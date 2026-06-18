"""Tests for alternative GitHub push credentials feature."""
import os
from unittest import mock

import pytest

from version_stamp.backends.git import _sanitize_log_str
from version_stamp.backends.git_ops import GitOpsMixin
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


class TestInjectCredentialsIntoUrl:
    """Test URL rewriting for various remote URL formats."""

    @pytest.fixture
    def mixin(self):
        m = GitOpsMixin()
        m._push_user = "deploy-bot"
        m._push_token = "ghp_abc123"
        return m

    def test_https_url(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://github.com/owner/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo.git"

    def test_https_url_no_dotgit_suffix(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://github.com/owner/repo"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo"

    def test_https_url_with_existing_credentials(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://old_user:old_token@github.com/owner/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo.git"

    def test_ssh_shorthand(self, mixin):
        result = mixin._inject_credentials_into_url(
            "git@github.com:owner/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo.git"

    def test_ssh_url(self, mixin):
        result = mixin._inject_credentials_into_url(
            "ssh://git@github.com/owner/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo.git"

    def test_github_enterprise_https(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://github.mycompany.com/org/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.mycompany.com/org/repo.git"

    def test_github_enterprise_ssh(self, mixin):
        result = mixin._inject_credentials_into_url(
            "git@github.mycompany.com:org/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.mycompany.com/org/repo.git"

    def test_https_url_with_port(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://github.com:443/org/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com:443/org/repo.git"

    def test_nested_path(self, mixin):
        result = mixin._inject_credentials_into_url(
            "https://github.com/org/sub/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/org/sub/repo.git"

    def test_special_characters_in_credentials(self):
        m = GitOpsMixin()
        m._push_user = "user@domain"
        m._push_token = "token/with+special&chars"
        result = m._inject_credentials_into_url(
            "https://github.com/owner/repo.git"
        )
        assert "user%40domain" in result
        assert "token%2Fwith%2Bspecial%26chars" in result
        assert result.startswith("https://")
        assert "@github.com/owner/repo.git" in result

    def test_local_file_path_returns_none(self, mixin):
        result = mixin._inject_credentials_into_url("/path/to/bare/repo.git")
        assert result is None

    def test_empty_url_returns_none(self, mixin):
        result = mixin._inject_credentials_into_url("")
        assert result is None

    def test_unsupported_protocol_returns_none(self, mixin):
        result = mixin._inject_credentials_into_url(
            "ftp://server.com/repo.git"
        )
        assert result is None

    def test_http_url_also_works(self, mixin):
        result = mixin._inject_credentials_into_url(
            "http://github.com/owner/repo.git"
        )
        assert result == "https://deploy-bot:ghp_abc123@github.com/owner/repo.git"


class TestGetPushTarget:
    """Test push target resolution with and without credentials."""

    def test_no_credentials_returns_remote_name(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        assert m._get_push_target() == "origin"

    def test_with_credentials_returns_authenticated_url(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        m.selected_remote.urls = ("https://github.com/o/r.git",)
        m.set_push_credentials("user", "token")
        assert m._get_push_target() == "https://user:token@github.com/o/r.git"

    def test_only_user_falls_back_to_remote(self):
        m = GitOpsMixin()
        m._push_user = "user"
        m._push_token = None
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        assert m._get_push_target() == "origin"

    def test_only_token_falls_back_to_remote(self):
        m = GitOpsMixin()
        m._push_user = None
        m._push_token = "token"
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        assert m._get_push_target() == "origin"

    def test_unsupported_url_falls_back_to_remote(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        m.selected_remote.urls = ("/local/path/repo.git",)
        m.set_push_credentials("user", "token")
        assert m._get_push_target() == "origin"

    def test_credentials_are_instance_scoped(self):
        m1 = GitOpsMixin()
        m1.set_push_credentials("user1", "token1")

        m2 = GitOpsMixin()
        assert m2._push_user is None
        assert m2._push_token is None


class TestSanitizeLogStr:
    """Test credential masking in log output."""

    def test_masks_https_credentials(self):
        s = "git push https://user:token@github.com/o/r.git refs/heads/main"
        assert _sanitize_log_str(s) == "git push https://***@github.com/o/r.git refs/heads/main"

    def test_masks_http_credentials(self):
        s = "git push http://user:token@host/r.git"
        assert _sanitize_log_str(s) == "git push http://***@host/r.git"

    def test_no_credentials_unchanged(self):
        s = "git push origin refs/heads/main:main"
        assert _sanitize_log_str(s) == s

    def test_masks_multiple_urls(self):
        s = "https://a:b@h1/r1 https://c:d@h2/r2"
        assert _sanitize_log_str(s) == "https://***@h1/r1 https://***@h2/r2"

    def test_plain_https_url_unchanged(self):
        s = "git push https://github.com/o/r.git"
        assert _sanitize_log_str(s) == s

    def test_masks_token_only_auth(self):
        s = "https://x-access-token:ghs_abc@github.com/o/r.git"
        assert _sanitize_log_str(s) == "https://***@github.com/o/r.git"


class TestCliArgParsing:
    """Test CLI argument parsing for credential flags."""

    def test_stamp_accepts_github_flags(self):
        from version_stamp.cli.args import parse_user_commands

        args = parse_user_commands(
            ["stamp", "-r", "patch", "--git-push-user", "u", "--git-push-token", "t", "app"]
        )
        assert args.git_push_user == "u"
        assert args.git_push_token == "t"

    def test_stamp_github_flags_default_to_none(self):
        from version_stamp.cli.args import parse_user_commands

        args = parse_user_commands(["stamp", "-r", "patch", "app"])
        assert args.git_push_user is None
        assert args.git_push_token is None

    def test_release_accepts_github_flags(self):
        from version_stamp.cli.args import parse_user_commands

        args = parse_user_commands(
            ["release", "--git-push-user", "u", "--git-push-token", "t", "app"]
        )
        assert args.git_push_user == "u"
        assert args.git_push_token == "t"

    def test_env_var_fallback(self):
        from version_stamp.cli.args import parse_user_commands

        args = parse_user_commands(["stamp", "-r", "patch", "app"])
        with mock.patch.dict(
            os.environ,
            {"VMN_GIT_PUSH_USER": "env_user", "VMN_GIT_PUSH_TOKEN": "env_token"},
        ):
            user = args.git_push_user or os.environ.get("VMN_GIT_PUSH_USER")
            token = args.git_push_token or os.environ.get("VMN_GIT_PUSH_TOKEN")
        assert user == "env_user"
        assert token == "env_token"

    def test_cli_flag_overrides_env_var(self):
        from version_stamp.cli.args import parse_user_commands

        args = parse_user_commands(
            ["stamp", "-r", "patch", "--git-push-user", "cli_user", "--git-push-token", "cli_token", "app"]
        )
        with mock.patch.dict(
            os.environ,
            {"VMN_GIT_PUSH_USER": "env_user", "VMN_GIT_PUSH_TOKEN": "env_token"},
        ):
            user = args.git_push_user or os.environ.get("VMN_GIT_PUSH_USER")
            token = args.git_push_token or os.environ.get("VMN_GIT_PUSH_TOKEN")
        assert user == "cli_user"
        assert token == "cli_token"


class TestPushWithCredentials:
    """Integration test: verify _push_with_ci_skip_fallback uses credentials."""

    def test_push_uses_authenticated_url(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        m.selected_remote.urls = ("https://github.com/org/repo.git",)
        m.set_push_credentials("bot", "ghp_secret")

        m._be = mock.MagicMock()
        m._push_with_ci_skip_fallback("refs/heads/main:main")

        call_args = m._be.git.execute.call_args_list[0][0][0]
        assert "https://bot:ghp_secret@github.com/org/repo.git" in call_args
        assert "origin" not in call_args

    def test_push_without_credentials_uses_remote_name(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"

        m._be = mock.MagicMock()
        m._push_with_ci_skip_fallback("refs/heads/main:main")

        call_args = m._be.git.execute.call_args_list[0][0][0]
        assert "origin" in call_args

    def test_push_fallback_on_ci_skip_failure(self):
        m = GitOpsMixin()
        m.selected_remote = mock.MagicMock()
        m.selected_remote.name = "origin"
        m.selected_remote.urls = ("https://github.com/org/repo.git",)
        m.set_push_credentials("bot", "ghp_secret")

        m._be = mock.MagicMock()
        m._be.git.execute.side_effect = [Exception("ci.skip not supported"), None]
        m._push_with_ci_skip_fallback("refs/tags/v1.0.0")

        # Second call (fallback) should also use authenticated URL
        call_args = m._be.git.execute.call_args_list[1][0][0]
        assert "https://bot:ghp_secret@github.com/org/repo.git" in call_args
        assert "-o" not in call_args
