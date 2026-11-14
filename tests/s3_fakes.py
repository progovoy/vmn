"""An in-memory S3 client: the boto3 subset ``version_stamp.store.s3_*`` uses."""
import datetime
import hashlib
import io

PAGE_SIZE = 2  # small, so every listing test pages
_MODIFIED = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


class FakeS3Error(Exception):
    """Shaped like botocore's ClientError: ``.response["Error"]["Code"]``."""

    def __init__(self, code, message=""):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


def _etag(body):
    return '"' + hashlib.md5(body).hexdigest() + '"'


class FakeS3Client:
    def __init__(self, missing_code="NoSuchKey"):
        self.objects = {}  # (bucket, key) -> bytes
        self.calls = []  # (operation, kwargs)
        self.missing_code = missing_code
        self.before_put = None  # called with the put's kwargs, before it applies

    def _record(self, op, kwargs):
        self.calls.append((op, dict(kwargs)))

    def _body(self, bucket, key):
        try:
            return self.objects[(bucket, key)]
        except KeyError:
            raise FakeS3Error(self.missing_code, key) from None

    def head_object(self, Bucket, Key):
        self._record("head_object", {"Bucket": Bucket, "Key": Key})
        try:
            body = self.objects[(Bucket, Key)]
        except KeyError:
            raise FakeS3Error("404", Key) from None
        return {"ContentLength": len(body), "ETag": _etag(body)}

    def get_object(self, Bucket, Key, Range=None):
        self._record("get_object", {"Bucket": Bucket, "Key": Key, "Range": Range})
        body = self._body(Bucket, Key)
        etag = _etag(body)
        if Range:
            body = body[int(Range[len("bytes="):].rstrip("-")):]
        return {"Body": io.BytesIO(body), "ETag": etag, "ContentLength": len(body)}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None):
        kwargs = {"Bucket": Bucket, "Key": Key, "Body": Body}
        kwargs.update({k: v for k, v in (("IfNoneMatch", IfNoneMatch), ("IfMatch", IfMatch)) if v})
        self._record("put_object", kwargs)
        if self.before_put:
            self.before_put(kwargs)
        current = self.objects.get((Bucket, Key))
        if IfNoneMatch == "*" and current is not None:
            raise FakeS3Error("PreconditionFailed", Key)
        if IfMatch is not None and (current is None or _etag(current) != IfMatch):
            raise FakeS3Error("412" if current is not None else self.missing_code, Key)
        self.objects[(Bucket, Key)] = bytes(Body)
        return {"ETag": _etag(bytes(Body))}

    def delete_object(self, Bucket, Key):
        self._record("delete_object", {"Bucket": Bucket, "Key": Key})
        self.objects.pop((Bucket, Key), None)
        return {}

    def delete_objects(self, Bucket, Delete):
        self._record("delete_objects", {"Bucket": Bucket, "Delete": Delete})
        for obj in Delete["Objects"]:
            self.objects.pop((Bucket, obj["Key"]), None)
        return {}

    def _entries(self, bucket, prefix, delimiter, start_after):
        """The listing's ``(kind, value)`` entries in key order."""
        entries, seen = [], set()
        for b, key in sorted(self.objects):
            if b != bucket or not key.startswith(prefix) or (start_after and key <= start_after):
                continue
            rest = key[len(prefix):]
            if delimiter and delimiter in rest:
                common = prefix + rest.split(delimiter, 1)[0] + delimiter
                if common not in seen:
                    seen.add(common)
                    entries.append(("prefix", common))
                continue
            body = self.objects[(b, key)]
            entries.append(("object", {"Key": key, "Size": len(body), "ETag": _etag(body),
                                       "LastModified": _MODIFIED}))
        return entries

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=1000,
                        StartAfter=None, ContinuationToken=None):
        self._record("list_objects_v2", {
            "Bucket": Bucket, "Prefix": Prefix, "Delimiter": Delimiter, "MaxKeys": MaxKeys,
            "StartAfter": StartAfter, "ContinuationToken": ContinuationToken})
        entries = self._entries(Bucket, Prefix, Delimiter, StartAfter)
        start = int(ContinuationToken or 0)
        end = start + min(MaxKeys, PAGE_SIZE)
        page = entries[start:end]
        result = {
            "Contents": [v for kind, v in page if kind == "object"],
            "CommonPrefixes": [{"Prefix": v} for kind, v in page if kind == "prefix"],
            "IsTruncated": end < len(entries),
        }
        if result["IsTruncated"]:
            result["NextContinuationToken"] = str(end)
        return result

    def keys(self, bucket):
        return sorted(k for b, k in self.objects if b == bucket)

    def ops(self, name):
        return [kwargs for op, kwargs in self.calls if op == name]
