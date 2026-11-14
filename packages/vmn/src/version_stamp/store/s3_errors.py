"""S3 error codes and write preconditions, without boto3: an error is anything
carrying a botocore-shaped ``response``."""

# The ``save_file_if_match`` token of a file that does not exist: the write
# only creates it (S3/Azure ``If-None-Match: *``, GCS generation 0). A
# ``load_file_with_token`` of a missing file returns it: ``(None, NO_FILE)``.
NO_FILE = "*"
MISSING_CODES = ("404", "NoSuchKey", "NotFound")
TAKEN_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")


def error_code(exc):
    return ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")


def is_missing(exc):
    """Whether *exc* says the object does not exist (not an access/transport error)."""
    return error_code(exc) in MISSING_CODES or "NoSuchKey" in str(exc)


def is_taken(exc):
    """Whether *exc* is a failed write precondition (someone else got there)."""
    return error_code(exc) in TAKEN_CODES


def put_condition(etag):
    """The ``put_object`` precondition of a write on version token *etag*
    (:data:`NO_FILE`: only create; none: unconditional)."""
    if etag == NO_FILE:
        return {"IfNoneMatch": "*"}
    return {"IfMatch": etag} if etag else {}
