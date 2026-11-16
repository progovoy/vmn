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


class EndpointConnectionError(Exception):
    """Shaped like botocore's transport errors: no ``response``, defined in botocore."""


EndpointConnectionError.__module__ = "botocore.exceptions"


class ProtocolError(Exception):
    """A urllib3 error a streamed body's ``read()`` can raise."""


ProtocolError.__module__ = "urllib3.exceptions"


class SubclassedEndpointError(EndpointConnectionError):
    pass


@pytest.mark.parametrize("exc", [
    FakeClientError("ExpiredToken"), FakeClientError("AccessDenied"),
    EndpointConnectionError("no route"), ProtocolError("reset"), SubclassedEndpointError(),
])
def test_s3_client_errors(exc):
    assert s3_errors.is_client_error(exc)


@pytest.mark.parametrize("exc", [
    ValueError("x"), KeyError("k"), AttributeError("a"), OSError("disk full"),
])
def test_bugs_and_local_errors_are_not_s3_client_errors(exc):
    assert not s3_errors.is_client_error(exc)


def test_the_refusal_of_an_error_response_is_its_code_and_message():
    exc = FakeClientError("AccessDenied", "ignored")
    exc.response["Error"]["Message"] = "Access Denied"
    assert s3_errors.refusal(exc) == ("AccessDenied", "Access Denied")


def test_an_error_response_without_a_message_refuses_with_the_error_text():
    assert s3_errors.refusal(FakeClientError("SignatureDoesNotMatch", "bad sig")) == (
        "SignatureDoesNotMatch", "bad sig")


def test_the_refusal_of_a_refused_delete_keeps_its_keys_and_codes():
    entry = {"Key": "p/k", "Code": "AccessDenied", "Message": "Access Denied"}
    assert s3_errors.refusal(s3_errors.S3DeleteRefused([entry])) == (
        "AccessDenied", f"S3 refused to delete 1 objects: {entry}")


@pytest.mark.parametrize("exc", [EndpointConnectionError("no route"), ProtocolError("reset"),
                                 ValueError("x")])
def test_no_response_is_no_refusal(exc):
    assert s3_errors.refusal(exc) is None


def test_real_botocore_errors_are_s3_client_errors():
    exceptions = pytest.importorskip("botocore.exceptions")
    assert s3_errors.is_client_error(exceptions.NoCredentialsError())
    assert s3_errors.is_client_error(exceptions.EndpointConnectionError(endpoint_url="http://x"))
    assert s3_errors.is_client_error(
        exceptions.ClientError({"Error": {"Code": "ExpiredToken"}}, "ListObjectsV2"))
