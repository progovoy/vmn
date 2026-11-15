"""``cold_start_notice``: what a first ``vmn-exp`` run commits, tags and pushes."""
from vmn_exp.gitmode.coldstart import cold_start_notice


def test_notice_counts_one_commit_when_only_the_app_is_new():
    notice = cold_start_notice("my_app", False, True, pushed=False, remote=None)

    assert "1 commit " in notice


def test_notice_counts_two_commits_when_the_repo_is_new_too():
    notice = cold_start_notice("my_app", True, True, pushed=False, remote=None)

    assert "2 commits" in notice


def test_notice_names_the_tag():
    notice = cold_start_notice("root/svc", True, True, pushed=False, remote=None)

    assert "root-svc_0.0.0" in notice


def test_notice_says_pushed_to_the_remote():
    notice = cold_start_notice("my_app", True, True, pushed=True, remote="origin")

    assert notice.endswith("pushed to origin.")


def test_notice_gives_the_push_command_when_nothing_was_pushed():
    notice = cold_start_notice("my_app", True, True, pushed=False, remote=None)

    assert "Nothing is pushed" in notice
    assert "git push --follow-tags" in notice
