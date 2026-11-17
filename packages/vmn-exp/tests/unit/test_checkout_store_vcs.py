"""Which app's vcs a store-only command (``model``, ``import-mlflow``) reads
its conf through, on a fake checkout: no cwd walk, no git."""
from fake_checkout import FakeCheckout
from vmn_exp.cli.checkout_store import _checkout_vcs


def test_outside_a_git_checkout_there_is_no_vcs():
    checkout = FakeCheckout(root=None, apps=["app"])
    assert _checkout_vcs("app", {}, checkout) is None
    assert checkout.built == []


def test_the_named_app_wins():
    assert _checkout_vcs("named", {"VMN_APP_NAME": "env"}, FakeCheckout(apps=["sole"])) == "vcs:named"


def test_the_environment_names_the_app_next():
    assert _checkout_vcs(None, {"VMN_APP_NAME": "env"}, FakeCheckout(apps=["sole"])) == "vcs:env"


def test_the_sole_stamped_app_comes_last():
    assert _checkout_vcs(None, {}, FakeCheckout(apps=["sole"])) == "vcs:sole"


def test_with_no_app_to_name_there_is_no_vcs():
    checkout = FakeCheckout(apps=["a", "b"])
    assert _checkout_vcs(None, {}, checkout) is None
    assert checkout.built == []
