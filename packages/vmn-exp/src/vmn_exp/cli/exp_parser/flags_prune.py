"""``prune``'s own flags (-v, --query, --dry-run and --force are shared)."""


def add_prune(parser):
    parser.add_argument("--keep", type=int, default=None,
                        help="Keep latest N experiments (for prune)")
    parser.add_argument("--older-than", default=None,
                        help="Prune experiments older than duration (e.g., 30d)")
    parser.add_argument("--local-only", action="store_true", default=False,
                        help="prune: delete local copies only, keep the remote (S3) ones")
    parser.add_argument("--protect-tag", dest="protect_tag", action="append", default=None,
                        help="prune: never delete a run carrying this tag key (repeatable)")
    parser.add_argument("--no-trim-journal", dest="no_trim_journal", action="store_true",
                        default=False,
                        help="prune --keep/--older-than/--query: leave the change journal "
                             "alone (a bucket whose lifecycle rule expires it); -v never "
                             "trims it")
    parser.add_argument("--yes", "-y", action="store_true", default=False,
                        help="prune --query: confirm deletion")
