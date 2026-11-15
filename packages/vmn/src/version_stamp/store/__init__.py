"""Record stores without git: the snapshot record format, store URIs and areas,
code objects and the S3 helpers core vmn and vmn-exp share
(docs/plans/45-s3-snapshot-store-in-core.md).

A leaf package: it imports only the standard library, ``yaml``,
``version_stamp.core.{utils,constants}`` and itself (boto3 only lazily) —
never git, ``version_stamp.snapshot``/``cli``/``devversion``/``stamping``/
``backends`` (``tests/test_store_imports.py``).
"""
