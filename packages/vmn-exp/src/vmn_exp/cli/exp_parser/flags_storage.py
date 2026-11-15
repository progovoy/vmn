"""Where the runs live: the store flags (shared with ``sweep``) and
``--from-snapshot``, which records against an exported tree without git."""


def add_from_snapshot(parser):
    parser.add_argument("--from-snapshot", default=None,
                        help="Path to vmn_metadata.yml or directory containing it. "
                             "Records against a tree from 'vmn-exp export' (no git "
                             "required). Falls back to VMN_SNAPSHOT_METADATA env var.")
