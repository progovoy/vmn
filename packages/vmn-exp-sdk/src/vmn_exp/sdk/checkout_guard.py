"""The one error a checkout-mode run raises outside a git checkout.

Checked before git mode is entered, so a plain directory is reported as such
rather than as a missing app name, a missing logger or a missing vmn-exp.
"""


def not_a_checkout(cwd):
    return (
        f"'{cwd}' is not inside a git checkout, and a run records the code it "
        "ran from one. Either make it a checkout "
        "(`git init && git commit --allow-empty -m init`), record against "
        "an exported tree by setting VMN_SNAPSHOT_METADATA, or record no code "
        "with start_run(code=False) / VMN_EXP_CODE=none (see sdk.md, "
        "'Runs without a git checkout')."
    )


def require_checkout(root, cwd):
    """*root* (the checkout's root), or RuntimeError when it is None."""
    if root is None:
        raise RuntimeError(not_a_checkout(cwd))
    return root
