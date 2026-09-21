"""vmn exp — experiment tracking: the CLI-facing SDK and its storage helpers.

Self-contained on purpose: this package depends on version_stamp.core and the
snapshot/storage helpers, never on version_stamp.ui, so the experiment feature
can be lifted out as its own distribution later.
"""
from version_stamp.exp.run import Run, start_run

__all__ = ["Run", "start_run"]
