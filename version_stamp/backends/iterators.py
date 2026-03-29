#!/usr/bin/env python3


class CommitMessageIterator:
    def __init__(self, iter_commits):
        self._iterator = iter(iter_commits)

    def __iter__(self):
        return self

    def __next__(self):
        commit = next(self._iterator)

        return commit.message.strip()


class CommitInfoIterator:
    """Iterator that yields (message, short_hash) tuples for changelog generation."""

    def __init__(self, iter_commits):
        self._iterator = iter(iter_commits)

    def __iter__(self):
        return self

    def __next__(self):
        commit = next(self._iterator)

        return commit.message.strip(), commit.hexsha[:7]
