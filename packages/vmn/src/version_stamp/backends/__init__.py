#!/usr/bin/env python3
"""VCS backend abstraction layer for vmn."""

from version_stamp.backends.base import VMNBackend  # noqa: F401
from version_stamp.backends.factory import get_client  # noqa: F401
from version_stamp.backends.git import GitBackend  # noqa: F401
from version_stamp.backends.iterators import (  # noqa: F401
    CommitInfoIterator,
    CommitMessageIterator,
)
from version_stamp.backends.local_file import LocalFileBackend  # noqa: F401
