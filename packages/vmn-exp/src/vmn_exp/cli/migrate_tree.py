"""Raw key access to a store being migrated: a local directory or an
S3-shaped object client (S3, and GCS/Azure through their adapters).

Keys are ``/``-separated and relative to the tree's base.
"""
import os
import shutil


class LocalTree:
    def __init__(self, base):
        self.base = base

    def _path(self, key):
        return os.path.join(self.base, *key.split("/"))

    def keys(self, prefix):
        top = self._path(prefix)
        found = []
        for d, _dirs, files in os.walk(top):
            rel = os.path.relpath(d, self.base).replace(os.sep, "/")
            found += [f"{rel}/{f}" for f in files]
        return sorted(found)

    def read(self, key):
        try:
            with open(self._path(key), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def write(self, key, data):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".migrate-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def transfer(self, src, dst):
        """A local move: no copy of the bytes."""
        os.makedirs(os.path.dirname(self._path(dst)), exist_ok=True)
        os.replace(self._path(src), self._path(dst))

    def delete_prefix(self, prefix):
        shutil.rmtree(self._path(prefix), ignore_errors=True)

    def prune_container(self, prefix, stop):
        """Drop a v1 records dir's per-host leftovers (``.gitignore``, index
        cache, push ledger), then the dir and its empty parents up to *stop*."""
        path = self._path(prefix)
        for name in os.listdir(path) if os.path.isdir(path) else []:
            if name.startswith("."):
                self.delete_prefix(f"{prefix}/{name}")
                if os.path.exists(os.path.join(path, name)):
                    os.unlink(os.path.join(path, name))
        stop = os.path.abspath(self._path(stop))
        while os.path.abspath(path) != stop and os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
            path = os.path.dirname(path)


class ObjectTree:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def keys(self, prefix):
        found, token = [], None
        while True:
            kw = {"ContinuationToken": token} if token else {}
            page = self.client.list_objects_v2(
                Bucket=self.bucket, Prefix=f"{prefix}/" if prefix else "", **kw)
            found += [o["Key"] for o in page.get("Contents", [])]
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated"):
                return found

    def read(self, key):
        from vmn_exp.storage.s3_base import is_missing

        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            if is_missing(e):
                return None
            raise

    def write(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def transfer(self, src, dst):
        self.write(dst, self.read(src))

    def delete_prefix(self, prefix):
        for key in self.keys(prefix):
            self.client.delete_object(Bucket=self.bucket, Key=key)

    def prune_container(self, prefix, stop):
        pass
