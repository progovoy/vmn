"""Who a run's features entry names (vmn_exp.core.fold_facts.author_display):
blank values are as missing as empty ones."""
import pytest
from vmn_exp.core.fold import author_display
from vmn_exp.core.log import experiment_row


@pytest.mark.parametrize("author, shown", [
    ({"git_user_email": " ", "os_user": "alice"}, "alice"),
    ({"git_user_email": "\t\n", "os_user": "  ", "writer": "gpu-07"}, "gpu-07"),
    ({"git_user_email": " ", "os_user": " ", "writer": " "}, None),
    ({"git_user_email": "  a@x.io  "}, "a@x.io"),
])
def test_whitespace_only_author_values_count_as_missing(author, shown):
    assert author_display(author) == shown


def test_a_row_of_a_blank_email_shows_the_os_user():
    log = [{"timestamp": "t0", "type": "create"},
           {"timestamp": "t1", "type": "features", "features_version": 1,
            "author": {"git_user_email": "   ", "os_user": "bob"}}]
    assert experiment_row(1, {"verstr": "v"}, log)["author"] == "bob"
