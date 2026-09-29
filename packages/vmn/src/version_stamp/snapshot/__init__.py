"""``vmn snapshot``: save points of uncommitted work, stored as thin records.

A snapshot record (``.vmn/<app>/snapshots/<verstr>/metadata.yml``) references
its code — patches and untracked tarball — by a ``code:`` key into the shared
code store (``vmn-code/<app~>`` records of the experiment-subdir store), the
same objects experiment runs use. The on-disk format is byte-compatible with
vmn-exp-sdk (``vmn_exp.storage.local`` / ``vmn_exp.core.code_store``), which
``version_stamp`` may never import; ``tests/test_snapshot_store_format.py``
keeps both copies in step.

Modules:
  - :mod:`.record`      record fields, file names, ``build_record_metadata``, ``same_state``
  - :mod:`.local_store` ``LocalRecordStore`` (the local backend)
  - :mod:`.code_store`  code-object keys and read/write helpers
  - :mod:`.refs`        ``resolve_snapshot_ref`` (latest, ``@N``, prefixes)
  - :mod:`.stores`      ``SnapshotStores`` / ``open_snapshot_stores``
"""
