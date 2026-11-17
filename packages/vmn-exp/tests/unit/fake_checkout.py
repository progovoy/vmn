"""A fake of the *checkout* :func:`vmn_exp.cli.checkout_store.command_storage`
takes (real one: ``CwdCheckout``): a git root, its stamped apps, and the vcs
built per app, recorded in ``built``."""


class FakeCheckout:
    def __init__(self, root="/repo", apps=()):
        self._root, self._apps, self.built = root, list(apps), []

    def git_root(self):
        return self._root

    def stamped_apps(self):
        return self._apps

    def vcs(self, app):
        self.built.append(app)
        return f"vcs:{app}"
