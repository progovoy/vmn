"""v1 store fixtures for the ``vmn-exp migrate`` tests, written in the old
layout directly (no old code), and the layout-2 keys they become."""
import datetime
import json
import os

import yaml

APP = "my/app"


def _jsonl(*entries):
    return "".join(json.dumps(e) + "\n" for e in entries).encode()


def _yml(data):
    return yaml.safe_dump(data).encode()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


IMAGE = {"type": "image", "name": "img", "step": 1, "path": "media/img/1.png"}
TABLE = {"type": "table", "name": "t", "step": 2, "path": "tables/t/2.json"}
FINISHED = {"state": "finished", "exit_code": 0}


def live_state():
    return {"state": "running", "heartbeat": _now(), "heartbeat_interval_sec": 30}


def run_files(verstr, state=FINISHED):
    return {
        "metadata.yml": _yml({"verstr": verstr, "code_verstr": "c1", "app_name": APP}),
        "run_state.yml": _yml(state),
        "log.w1.jsonl": _jsonl({"type": "create"}, IMAGE),
        "log.w1@000001.jsonl": _jsonl(TABLE),
        "log.yml": _yml([{"type": "note", "text": "old"}]),
        "artifacts/output.log": b"hello\n",
        "artifacts/media/img/1.png": b"PNG",
        "artifacts/tables/t/2.json": b"{}",
        "artifacts/model.bin": b"weights",
    }


def v1_records(live=False):
    """``[(location, record name, files)]`` of a v1 store."""
    records = [
        (("run",), "r1", run_files("r1")),
        (("snap",), "s1", {"metadata.yml": _yml({"verstr": "s1", "app_name": APP})}),
        (("code",), "c1.abc", {"metadata.yml": _yml({"verstr": "c1"}),
                               "working_tree.patch": b"diff"}),
        (("sweep", "sw1"), "t0", {"metadata.yml": _yml({"verstr": "t0"})}),
        (("registry",), "m1", {"metadata.yml": _yml({"model": "m1"})}),
        (("registry",), "m1.v1", {"metadata.yml": _yml({"version": 1})}),
        (("registry",), "m1-uses", {"metadata.yml": _yml({}),
                                    "log.u.jsonl": _jsonl({"type": "use"})}),
    ]
    if live:
        records.append((("run",), "r2", run_files("r2", live_state())))
    return records


def local_key(loc, rec):
    """A v1 repo-local key, relative to the dir holding ``.vmn``."""
    kind = loc[0]
    if kind in ("run", "snap"):
        sub = "experiments" if kind == "run" else "snapshots"
        return f".vmn/{APP}/{sub}/{rec}"
    if kind == "code":
        return f".vmn/vmn-code/my~app/experiments/{rec}"
    if kind == "sweep":
        return f".vmn/vmn-sweeps/my~app~{loc[1]}/experiments/{rec}"
    return f".vmn/vmn-registry/experiments/{rec}"


def object_key(loc, rec, path=None):
    """A v1 object-store key: under *path*, or the v1 default prefixes."""
    kind = loc[0]
    base = path or ("vmn-snapshots" if kind == "snap" else "vmn-experiments")
    seg = {"run": "my-app", "snap": "my-app", "code": "vmn-code-my~app",
           "registry": "vmn-registry"}.get(kind) or f"vmn-sweeps-my~app~{loc[1]}"
    return f"{base}/{seg}/{rec}"


def v2_prefix(loc, rec):
    kind = loc[0]
    if kind == "registry":
        if rec.endswith("-uses"):
            return f"registry/{rec[:-5]}/uses"
        model, dot, n = rec.partition(".v")
        return f"registry/{model}/v{n}" if dot else f"registry/{rec}/header"
    area = {"run": "runs", "snap": "snapshots", "code": "code"}.get(kind)
    if area:
        return f"{area}/my-app/{rec}"
    return f"sweeps/my-app~{loc[1]}/{rec}"


V2_RUN_FILES = {
    "metadata.yml", "run_state.yml", "log/w1.jsonl", "log/w1@000001.jsonl",
    "log/v1.jsonl", "outputs/output.log", "outputs/media/img/1.png",
    "outputs/tables/t/2.json", "artifacts/model.bin",
}


def expected_v2_keys(records):
    keys = set()
    for loc, rec, files in records:
        names = V2_RUN_FILES if loc[0] == "run" else {
            "log/" + n[4:] if n.startswith("log.") else n for n in files}
        keys |= {f"{v2_prefix(loc, rec)}/{n}" for n in names}
    return keys


def write_v1(put, key_of, records):
    for loc, rec, files in records:
        for name, data in files.items():
            put(f"{key_of(loc, rec)}/{name}", data)


class LocalRaw:
    """Raw file access below *base*, keys ``/``-separated."""

    def __init__(self, base):
        self.base = str(base)

    def put(self, key, data):
        path = os.path.join(self.base, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def get(self, key):
        with open(os.path.join(self.base, key), "rb") as f:
            return f.read()

    def keys(self, under=""):
        top = os.path.join(self.base, under)
        found = set()
        for d, _dirs, files in os.walk(top):
            for f in files:
                found.add(os.path.relpath(os.path.join(d, f), top).replace(os.sep, "/"))
        return found


class ObjectRaw:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def keys(self, under=""):
        prefix = f"{under}/" if under else ""
        found, token = set(), None
        while True:
            kw = {"ContinuationToken": token} if token else {}
            page = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix, **kw)
            found |= {o["Key"][len(prefix):] for o in page.get("Contents", [])}
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated"):
                return found


def log_paths(raw, key):
    return [json.loads(line).get("path") for line in raw.get(key).decode().splitlines()]
