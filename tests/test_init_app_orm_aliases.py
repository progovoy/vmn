"""`init-app --release-mode-policy` / `--default-release-mode` are aliases of --orm."""
import pytest
from helpers import _run_vmn_init
from version_stamp.cli.args import parse_user_commands
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger

ALIASES = ["--orm", "--release-mode-policy", "--default-release-mode"]


@pytest.mark.parametrize("flag", ALIASES)
@pytest.mark.parametrize("policy", ["optional", "strict"])
def test_alias_parses_into_orm(flag, policy):
    args = parse_user_commands(["init-app", flag, policy, "app"])

    assert args.orm == policy


@pytest.mark.parametrize("flag", ALIASES)
def test_alias_rejects_unknown_policy(flag):
    with pytest.raises(SystemExit):
        parse_user_commands(["init-app", flag, "sometimes", "app"])


def test_orm_defaults_to_optional():
    assert parse_user_commands(["init-app", "app"]).orm == "optional"


@pytest.mark.parametrize("flag", ALIASES)
def test_alias_sets_the_release_mode_policy_on_init_app(app_layout, flag):
    _run_vmn_init()
    reset_logger()

    err, vmn_ctx = vmn_run(["init-app", flag, "strict", app_layout.app_name])

    assert err == 0
    assert vmn_ctx.vcs.release_mode_policy == "strict"
