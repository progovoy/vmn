"""The S3 client parses response timestamps without dateutil: botocore's
default parser spent ~25 µs per timestamp, a LIST of 1000 objects ~25 ms of
GIL-held CPU, which starved a cold index's loads behind its listing."""
import datetime

import pytest
from botocore.utils import parse_timestamp
from s3_helpers import meta, mocked_bucket, s3_storage

from vmn_exp.storage import s3_base


@pytest.mark.parametrize("text", [
    "2026-10-27T06:57:22.000Z", "2026-10-27T06:57:22Z", "2026-10-27T06:57:22.123456Z",
    "Tue, 27 Oct 2026 06:57:22 GMT", "2026-10-27T06:57:22+02:00", "1793000000",
])
def test_timestamps_parse_as_botocore_does(text):
    assert s3_base.parse_timestamp(text).timestamp() == parse_timestamp(text).timestamp()


def test_the_client_parses_with_it(monkeypatch):
    seen = []
    real = s3_base.parse_timestamp
    monkeypatch.setattr(s3_base, "parse_timestamp", lambda v: seen.append(v) or real(v))
    with mocked_bucket(monkeypatch):
        storage = s3_storage()
        storage.save("app", "v1", meta("v1"), {})
        files = storage.list_files("app", keys=["v1"])
    assert seen
    when = files["v1"]["metadata.yml"][1]
    assert abs(when - datetime.datetime.now(datetime.timezone.utc).timestamp()) < 600
