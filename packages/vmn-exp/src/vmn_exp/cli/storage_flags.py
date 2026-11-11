"""The store flags of the commands that open experiment storage."""


def _add_storage_args(parser):
    """Add common storage flags to a subcommand parser."""
    parser.add_argument(
        "--dir",
        default=None,
        help="Experiment storage directory (overrides VMN_EXPERIMENT_DIR)",
    )
    add_storage_flags(parser)


def add_storage_flags(parser):
    """The store flags every storage-opening command takes. ``--prefix`` has
    no default: :func:`store_uri` supplies it, so an explicit one always wins."""
    parser.add_argument("--store", default=None,
                        help="Storage URI: s3://bucket/prefix, gs://..., az://..., "
                             "file:///dir (or VMN_EXPERIMENT_STORE)")
    parser.add_argument("--bucket", default=None,
                        help="S3 bucket name (shorthand for --store s3://BUCKET/PREFIX)")
    parser.add_argument("--prefix", default=None,
                        help="S3 key prefix: the store root (default: vmn)")
    parser.add_argument("--endpoint-url", dest="endpoint_url", default=None,
                        help="Custom S3 endpoint URL")
