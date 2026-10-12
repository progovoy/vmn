#!/usr/bin/env python3
"""Which streams a local record copy appends to (:mod:`stream_owner`): its
owner's, until that owner's metric stream is compacted — then a new owner's,
so no block is ever appended behind a ``.vmx``."""
from vmn_exp.core.metric_files import is_indexed_file
from vmn_exp.core.streams import display_writer, owner_of, stream_key
from vmn_exp.storage import stream_owner


class LocalStreams:
    def _owner_dir(self, app_name, verstr):
        return self._snapshot_dir(app_name, verstr) if self.exists(app_name, verstr) else None

    def stream_owner(self, app_name, verstr, writer):
        """The owner of the copy's streams; None without a local copy."""
        record = self._owner_dir(app_name, verstr)
        if record is None:
            return None
        owner = stream_owner.record_owner(record)
        if self._compacted(app_name, verstr, stream_key(writer, owner)):
            owner = stream_owner.retire_owner(record, owner)
        return owner

    def _compacted(self, app_name, verstr, stream):
        objects = self.metric_objects(app_name, verstr).get(stream, ())
        return any(is_indexed_file(name) for name, _ in objects)

    def stream_owners(self, app_name, verstr):
        """The owners of the copy's own streams (its owner, the retired ones);
        a ``cp -r`` copy holds only a stale prefix of the others'."""
        record = self._owner_dir(app_name, verstr)
        state = stream_owner.read_state(record) if record else None
        return {state["id"], *state.get("retired", ())} if state else set()

    def inherited_owners(self, app_name, verstr):
        """The owners whose streams came with the copy's directory (a ``cp
        -r``, a move) or are another view's: never appended to, shipped,
        pushed nor compacted here until adopted (:mod:`vmn_exp.core.adopt`)."""
        record = self._owner_dir(app_name, verstr)
        return stream_owner.inherited(record) if record else set()

    def retire_stream(self, app_name, verstr, stream):
        """Before *stream* is compacted: the copy moves on to a new owner if
        *stream* is its current one."""
        record = self._owner_dir(app_name, verstr)
        if record is not None and owner_of(stream):
            stream_owner.retire_owner(record, owner_of(stream))

    def live_stream(self, app_name, verstr, stream):
        """*stream*, or the copy's current stream of its writer when the copy
        retired *stream*'s owner."""
        record = self._owner_dir(app_name, verstr)
        owner = owner_of(stream)
        if record is None or not owner:
            return stream
        state = stream_owner.read_state(record)
        if state is None or owner not in state.get("retired", ()):
            return stream
        return stream_key(display_writer(stream), state["id"])
