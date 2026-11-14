"""``version_stamp.store.s3_errors``: S3 error codes and write preconditions,
pure (no boto3: an error is anything with a botocore-shaped ``response``)."""
import pytest

from version_stamp.store import s3_errors


class FakeClientError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message)
        self.response = {"Error": {"Code": code}}


def test_error_code_reads_the_response():
    assert s3_errors.error_code(FakeClientError("404")) == "404"
    assert s3_errors.error_code(ValueError("x")) is None


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_missing_codes(code):
    assert s3_errors.is_missing(FakeClientError(code))


def test_a_no_such_key_message_is_missing_too():
    assert s3_errors.is_missing(ValueError("An error occurred (NoSuchKey)"))


def test_access_denied_is_not_missing():
    assert not s3_errors.is_missing(FakeClientError("AccessDenied"))


@pytest.mark.parametrize("code", ["412", "PreconditionFailed", "409", "ConditionalRequestConflict"])
def test_taken_codes(code):
    assert s3_errors.is_taken(FakeClientError(code))


def test_a_missing_object_is_not_taken():
    assert not s3_errors.is_taken(FakeClientError("404"))


def test_put_condition_per_token():
    assert s3_errors.NO_FILE == "*"
    assert s3_errors.put_condition(s3_errors.NO_FILE) == {"IfNoneMatch": "*"}
    assert s3_errors.put_condition('"etag"') == {"IfMatch": '"etag"'}
    assert s3_errors.put_condition(None) == {}
