"""How ``list`` orders and cuts its rows (``--top`` also on compare and similar)."""


def add_sort(parser):
    parser.add_argument("--sort", default=None,
                        help="Sort list by a metric name, newest first by "
                             "timestamp/started_at/finished_at/idx, or ascending by "
                             "a row field (duration_sec, queue_sec, ...), tags.<k> "
                             "or params.<k>")


def add_top(parser):
    parser.add_argument("--top", type=int, default=None,
                        help="list: show the top N results; similar: how many runs to show "
                             "(default 10)")
