"""``vmn snapshot``: save points of uncommitted work, stored as thin records.

A snapshot record (``.vmn/store/snapshots/<app-key>/<verstr>/metadata.yml``) references
its code — patches and untracked tarball — by a ``code:`` key into the shared
code store (``.vmn/store/code/<app-key>/<code_verstr>.<diff hash>/``), the
same objects experiment runs use. The on-disk format is byte-compatible with
vmn-exp-sdk (``vmn_exp.storage.local`` / ``vmn_exp.core.code_store``), which
``version_stamp`` may never import; ``tests/test_snapshot_store_format.py``
keeps both copies in step.

Modules:
  - :mod:`.record`      record fields, file names, ``build_record_metadata``, ``same_state``
  - :mod:`.identity`    record names, diff hashes, dev verstrs (a leaf module)
  - :mod:`.local_store` ``LocalRecordStore`` (the local backend)
  - :mod:`.code_store`  code-object keys and read/write helpers
  - :mod:`.refs`        ``resolve_snapshot_ref`` (latest, ``@N``, prefixes)
  - :mod:`.stores`      ``SnapshotStores`` / ``open_snapshot_stores``
  - :mod:`.create`      ``vmn snapshot create`` (thin record + shared code object)
  - :mod:`.listing`     ``list`` / ``show`` / ``note``, ``relative_timestamp``
  - :mod:`.delete`      ``delete`` (drops the code object once unreferenced)
  - :mod:`.load`        ``load_snapshot`` (refuses missing code), ``stamped_state``
  - :mod:`.restore`     ``restore`` (auto-saves the replaced work first)
  - :mod:`.export`      ``export`` (materialized tree to a dir or tarball)
  - :mod:`.diff`        ``diff`` (vs the working state, a snapshot or a stamped version)
"""
