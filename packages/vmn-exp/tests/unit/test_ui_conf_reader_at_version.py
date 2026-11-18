"""The config view at a version shows the conf vmn loaded when it stamped
that version: the branch conf of the branch it was stamped on, as recorded
at its tag, else the tag's conf.yml."""
from vmn_exp.ui.readers.config import conf_text_at

_APP_CONF = ".vmn/app/conf.yml"
_BRANCH_CONF = ".vmn/app/branch_conf/feat/x/conf.yml"


def _show(files):
    return files.get


def test_the_stamping_branchs_conf_wins():
    files = {_APP_CONF: "app", _BRANCH_CONF: "branch"}
    assert conf_text_at(_show(files), "app", "feat/x") == "branch"


def test_without_a_branch_conf_at_the_tag_the_app_conf_is_shown():
    assert conf_text_at(_show({_APP_CONF: "app"}), "app", "feat/x") == "app"


def test_a_version_with_no_recorded_branch_shows_the_app_conf():
    files = {_APP_CONF: "app", _BRANCH_CONF: "branch"}
    assert conf_text_at(_show(files), "app", None) == "app"


def test_a_tag_without_any_conf_shows_none():
    assert conf_text_at(_show({}), "app", "feat/x") is None


def test_a_root_service_reads_under_its_nested_app_dir():
    files = {".vmn/root/svc/branch_conf/main/conf.yml": "svc"}
    assert conf_text_at(_show(files), "root/svc", "main") == "svc"
