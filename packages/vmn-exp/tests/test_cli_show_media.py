"""``vmn-exp show`` summarizes a run's logged images, tables and histograms."""
from vmn_exp.cli.experiment import _describe_log_entry
from vmn_exp.cli.media_view import media_lines
from vmn_exp.cli.views import show_payload

LOG = [
    {"type": "image", "name": "s", "step": 0, "path": "media/s/0.png"},
    {"type": "image", "name": "s", "step": 1, "path": "media/s/1.png"},
    {"type": "table", "name": "t", "step": 0, "path": "tables/t/0.json", "rows": 5},
    {"type": "histogram", "name": "w", "step": 3, "bins": [0, 1], "counts": [4]},
]


def test_media_lines_count_entries_and_keys():
    assert media_lines(LOG) == ["images: 2 (1 key)", "tables: 1 (1 key)", "histograms: 1 (1 key)"]


def test_media_lines_are_empty_without_media():
    assert media_lines([{"type": "metrics", "values": {"a": 1}}]) == []


def test_log_entries_describe_media():
    assert _describe_log_entry(LOG[0]) == "image: s @ step 0 (media/s/0.png)"
    assert _describe_log_entry(LOG[2]) == "table: t @ step 0 (5 rows)"
    assert _describe_log_entry(LOG[3]) == "histogram: w @ step 3 (1 bins)"


def test_show_json_carries_media_counts():
    payload = show_payload(1, {"verstr": "v"}, {}, LOG, None, {})
    assert payload["media_counts"]["images"] == {"keys": 1, "entries": 2}
