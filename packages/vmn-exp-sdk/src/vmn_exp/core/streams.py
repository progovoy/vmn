#!/usr/bin/env python3
"""Stream keys: the names of a record's per-writer log and metric streams.

A stream is ``<writer id>~<owner>``: the writer id the user sees (the host,
``VMN_WRITER_ID``), and the owner that appends to it — a local copy of the
record (:mod:`vmn_exp.storage.stream_owner`), or a process writing straight
to a remote. Each stream thus has exactly one appending owner, and its remote
copy is a replica of that owner's local file (docs/plans/20-per-root-streams.md).
A hostname never contains ``~``; an explicit writer id has it replaced.
Pure: no I/O.
"""
import os
import secrets

STREAM_SEP = "~"
_PROCESS = {"pid": None, "owner": None}


def stream_key(writer, owner):
    return f"{writer}{STREAM_SEP}{owner}"


def display_writer(stream):
    """The writer id of *stream* (a plain name is its own writer)."""
    return stream.partition(STREAM_SEP)[0]


def owner_of(stream):
    """The owner part of *stream* ('' for a plain name)."""
    return stream.partition(STREAM_SEP)[2]


def clean_writer_id(writer):
    """*writer* usable in a stream key: its ``~`` replaced."""
    return writer.replace(STREAM_SEP, "-")


def new_owner():
    return secrets.token_hex(4)


def process_owner():
    """This process's owner id (a forked child gets its own)."""
    if _PROCESS["pid"] != os.getpid():
        _PROCESS.update(pid=os.getpid(), owner=new_owner())
    return _PROCESS["owner"]
