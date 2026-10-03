# Bring your own bucket

A `vmn-exp ui` server ([server.md](server.md)) reads your object store
(S3, GCS, Azure, MinIO) with an identity you grant it. Your data stays in your
bucket. This page lists what to grant.

## Who accesses what

- **Jobs** write runs straight to the bucket with the storage access their
  environment already has: instance roles, Kubernetes workload identity, keys
  in the environment. Storage is configured as usual (`--store` >
  `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri`). Jobs never contact
  the server, and nothing about job setup changes when a server is added.
- **The server** reads the bucket with its own identity: a service account,
  an instance role, or a role you let it assume. It never issues, mints or
  hands out storage credentials, to jobs or to anyone else.
- **People** use the UI. vmn roles (`viewer`/`editor`/`admin`) only govern
  what they can do *through vmn*. Direct bucket access is your IAM. The
  recommended setup gives humans no direct bucket access and gives jobs write
  access through their compute identity.

## Store layout: areas

Every store root (`s3://bucket/prefix`; a URI without a path uses the root
`vmn`) has the same top-level folders, so permissions are plain prefix lists:

| Area | Holds | Written by |
|---|---|---|
| `store.yml` | layout marker (created by the first writer) | first writer |
| `runs/<app-key>/<verstr>/` | experiment runs | jobs; server edits `metadata.yml` and its own log files |
| `snapshots/<app-key>/<verstr>/` | `vmn snapshot` records | users, jobs |
| `code/<app-key>/<code_verstr>.<diff_hash>/` | shared code objects | jobs |
| `sweeps/<app-key>~<sweep>/<slot>/` | sweep trial claims | sweep agents |
| `registry/<model>/<record>/` | model and dataset registry | CLI/SDK, server edits |
| `reports/<rid>/...` | reports and their comment threads ([reports.md](reports.md)) | server, `vmn-exp report put` |
| `comments/<app-key>/<verstr>/` | run comment threads | server, `vmn-exp comment` |
| `journal/<YYYYMMDDHHMM>/...` | change journal: empty objects naming changed records | every writer, including the server |
| `server/` | the server's probe key | server (read + edits only) |

`<app-key>` is the app name with `/` replaced by `-`. A v1 store (records but
no `store.yml`) is refused until you convert it with
`vmn-exp migrate --store <uri> [--dry-run] [--skip-live]`.

## The server's two permission sets

Neither set includes deletes. Prune and delete stay CLI actions, run under
your own access.

| Set | Grants | The UI can |
|---|---|---|
| **Read-only** | list and get under `<prefix>/` | browse, compare, charts, search, comment counts. Edit requests get `403` |
| **Read + edits** | the above, plus put on: `runs/*/*/metadata.yml`, `runs/*/*/log/vmn-server*`, `registry/*`, `reports/*`, `comments/*`, `journal/*`, `server/*` | also tag, note, archive, rewind, model register/alias/deprecate, reports and comments |

- `runs/*/*/log/<writer>*` is the server's own per-writer log, which rewind
  markers go to. A process's writer id is `VMN_WRITER_ID`, else `$HOSTNAME`,
  else the host name. Run the server with `VMN_WRITER_ID=vmn-server` to match
  the policy below, or put your own id in the policy.
- `journal/*` lets the server's edits show up the way any writer's do.
- `server/*` holds the probe key. Before the first edit, the server checks
  `read` by listing `runs/` and `edit` by a create-if-absent write under
  `server/probe/`. It only offers what the probe confirms.

Jobs typically need write on `runs/ snapshots/ code/ sweeps/ journal/` and
read on `registry/` (write too if jobs register models or datasets).

### Example: S3 read + edits policy

For bucket `acme-ml` and prefix `vmn`. Drop the last statement for the
read-only set.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": ["arn:aws:s3:::acme-ml"],
      "Condition": {"StringLike": {"s3:prefix": ["vmn/*"]}}
    },
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::acme-ml/vmn/*"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": [
        "arn:aws:s3:::acme-ml/vmn/runs/*/*/metadata.yml",
        "arn:aws:s3:::acme-ml/vmn/registry/*",
        "arn:aws:s3:::acme-ml/vmn/reports/*",
        "arn:aws:s3:::acme-ml/vmn/comments/*",
        "arn:aws:s3:::acme-ml/vmn/runs/*/*/log/vmn-server*",
        "arn:aws:s3:::acme-ml/vmn/journal/*",
        "arn:aws:s3:::acme-ml/vmn/server/*"
      ]
    }
  ]
}
```

If the server runs in another AWS account and assumes a role in yours, require
an external id in the role's trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::<server-account-id>:root"},
    "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"sts:ExternalId": "<external-id>"}}
  }]
}
```

The same documents, plus CloudFormation and Terraform renderings, come from
`vmn_exp.ui.onboarding` (`permission_policy(bucket, prefix, edits=)`,
`trust_policy`, `lifecycle_rule`, `cors_rules`, `cloudformation`,
`terraform`). These are Python helpers. There is no CLI command for them.

On GCS and Azure, grant the same prefixes to the server's service account or
managed identity: object read and list on the prefix, plus object create on
the edit paths for read + edits.

## Journal lifecycle rule

Journal objects are empty and only useful for a few minutes, but they pile up.
The server never deletes them. `vmn-exp prune` drops journal partitions older
than 2 days. On object stores, also expire them with a lifecycle rule on the
literal prefix `<prefix>/journal/`:

```json
{
  "Rules": [{
    "ID": "vmn-journal-expiry",
    "Filter": {"Prefix": "vmn/journal/"},
    "Status": "Enabled",
    "Expiration": {"Days": 2}
  }]
}
```

```sh
aws s3api put-bucket-lifecycle-configuration --bucket acme-ml \
  --lifecycle-configuration file://lifecycle.json
```

GCS: a `Delete` rule with `age: 2` and `matchesPrefix: ["vmn/journal/"]`.
Azure: a lifecycle management rule with `prefixMatch: ["<container>/vmn/journal/"]`
and delete after 2 days.

## CORS for redirect downloads

With `downloads: redirect` on a workspace ([server.md](server.md#serveryml)),
the browser fetches artifacts and media from presigned URLs. Allow `GET` from
the dashboard's origin:

```json
{"CORSRules": [{
  "AllowedMethods": ["GET"],
  "AllowedOrigins": ["https://vmn.example.com"],
  "AllowedHeaders": ["*"],
  "MaxAgeSeconds": 300
}]}
```

With the default `downloads: stream`, no CORS is needed.

## What the server keeps outside your bucket

The server's cache ([server.md](server.md#the-cache)) holds derived run rows:
params, metric summaries, tags, notes, status. Logs, metric series, artifacts,
media and code are read from the bucket on demand and are only held in bounded
in-memory caches. The cache can be deleted at any time and is rebuilt from the
bucket. The control-plane DB holds workspaces, API tokens, sessions and the
audit log, and no run data.
