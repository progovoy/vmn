"""`--metrics` on the experiment parser: a repeated flag adds to the earlier
one, so the ui can emit one attached `--metrics=<k>=<v>` token per metric."""
from version_stamp.cli.args import parse_user_commands
from vmn_exp.cli.plugin import register_all


def _metrics(*tokens):
    register_all()
    return parse_user_commands(["experiment", "create", "my_app", *tokens]).metrics


def test_repeated_attached_metrics_accumulate():
    assert _metrics("--metrics=loss=0.3", "--metrics=acc=0.9") == ["loss=0.3", "acc=0.9"]


def test_space_separated_metrics_still_parse():
    assert _metrics("--metrics", "loss=0.3", "acc=0.9") == ["loss=0.3", "acc=0.9"]


def test_attached_and_separate_forms_mix():
    assert _metrics("--metrics=loss=0.3", "--metrics", "acc=0.9", "lr=1e-3") == [
        "loss=0.3", "acc=0.9", "lr=1e-3"]
