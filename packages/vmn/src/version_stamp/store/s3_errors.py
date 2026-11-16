"""S3 error codes and write preconditions, without boto3: an error is anything
carrying a botocore-shaped ``response`` (or, for :func:`is_client_error`, a
botocore/urllib3 exception class)."""

# The ``save_file_if_match`` token of a file that does not exist: the write
# only creates it (S3/Azure ``If-None-Match: *``, GCS generation 0). A
# ``load_file_with_token`` of a missing file returns it: ``(None, NO_FILE)``.
NO_FILE = "*"
MISSING_CODES = ("404", "NoSuchKey", "NotFound")
TAKEN_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")
# Where the S3 client's own errors are defined: botocore's credential/transport
# errors, and urllib3's, which a streamed body's ``read()`` can raise.
CLIENT_ERROR_MODULES = ("botocore.", "urllib3.")


class S3DeleteRefused(RuntimeError):
    """S3 refused keys of a ``delete_objects`` batch; *errors* its ``Errors``
    entries (``Key``, ``Code``, ``Message``)."""

    def __init__(self, errors):
        super().__init__(f"S3 refused to delete {len(errors)} objects: {errors[0]}")
        self.errors = errors


def error_code(exc):
    return ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")


def is_missing(exc):
    """Whether *exc* says the object does not exist (not an access/transport error)."""
    return error_code(exc) in MISSING_CODES or "NoSuchKey" in str(exc)


def is_taken(exc):
    """Whether *exc* is a failed write precondition (someone else got there)."""
    return error_code(exc) in TAKEN_CODES


def is_client_error(exc):
    """Whether the S3 client raised *exc* (an error response, credentials,
    network), not a bug or a local error."""
    if error_code(exc) is not None or isinstance(exc, S3DeleteRefused):
        return True
    return any(cls.__module__.startswith(CLIENT_ERROR_MODULES) for cls in type(exc).__mro__)


def refusal(exc):
    """``(code, message)`` when S3 answered *exc* with an error (it was
    reached and refused); None when no response came back."""
    if isinstance(exc, S3DeleteRefused):
        return exc.errors[0].get("Code"), str(exc)
    code = error_code(exc)
    if code is None:
        return None
    return code, exc.response["Error"].get("Message") or str(exc)


def put_condition(etag):
    """The ``put_object`` precondition of a write on version token *etag*
    (:data:`NO_FILE`: only create; none: unconditional)."""
    if etag == NO_FILE:
        return {"IfNoneMatch": "*"}
    return {"IfMatch": etag} if etag else {}
