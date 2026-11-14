#!/usr/bin/env python3
"""S3 record writes: core's (:class:`~version_stamp.store.s3_records.S3RecordWrites`
— ``metadata.yml`` written last and deleted first, names claimed by a
``.claim`` object under ``If-None-Match``), stamped with the record format
this SDK writes (:mod:`vmn_exp.core.record_format`: 2) instead of core's 1.
"""

from version_stamp.store.s3_records import (  # noqa: F401  (re-exported)
    CLAIM_FILE,
    DELETE_BATCH,
    S3RecordWrites,
)
from vmn_exp.core.record_format import with_format_version

_DELETE_BATCH = DELETE_BATCH  # the most keys one DeleteObjects takes (patchable)


class S3Records(S3RecordWrites):
    _stamped = staticmethod(with_format_version)

    def _delete_keys(self, keys):
        """Delete *keys*: batches of :data:`_DELETE_BATCH`, sent concurrently."""
        batches = [keys[i : i + _DELETE_BATCH] for i in range(0, len(keys), _DELETE_BATCH)]
        self._map(self._delete_batch, batches)
