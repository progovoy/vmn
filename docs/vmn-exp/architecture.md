# Architecture

How vmn-exp fits together: the three packages, the store they share, how a run
is recorded, and how clients use it, from a laptop to a fleet of pods. The
diagrams are Mermaid, so they render on GitHub and in most Markdown viewers.

- [The big picture](#the-big-picture)
- [Three packages, one store](#three-packages-one-store)
- [How clients use it](#how-clients-use-it)
- [The life of a run](#the-life-of-a-run)
- [Outer runs and inner runs](#outer-runs-and-inner-runs)
- [Inside the store](#inside-the-store)
- [How the dashboard reads the store](#how-the-dashboard-reads-the-store)

---

## The big picture

The store is the source of truth. Everything else writes to it or reads from
it. No component talks to another over the network: jobs never contact the
dashboard, and the dashboard never hands jobs credentials.

```mermaid
flowchart LR
    subgraph dev["💻 Developer machine (git checkout)"]
        direction TB
        vmn["<b>vmn</b><br/>versions in git tags<br/><code>vmn stamp</code> · <code>vmn snapshot</code> · <code>vmn goto</code>"]
        cli["<b>vmn-exp CLI</b><br/><code>run</code> · <code>list</code> · <code>compare</code> · <code>rerun</code><br/><code>sweep</code> · <code>model</code> · <code>push</code>"]
        cli -- "snapshot + auto-init<br/>via version_stamp.api" --> vmn
    end

    subgraph jobs["⚙️ Training jobs (laptop, Slurm, Kubernetes)"]
        direction TB
        sdk["<b>vmn-exp-sdk</b><br/><code>start_run()</code> · <code>log_metric()</code><br/>autolog · heartbeat · sync"]
    end

    store[("🗄️ <b>Store</b><br/><code>.vmn/store/</code> · <code>file://</code><br/><code>s3://</code> · <code>gs://</code> · <code>az://</code>")]

    subgraph view["📊 Dashboard"]
        direction TB
        ui["<b>vmn-exp ui</b><br/>REST API + web app<br/>index cache (memory / SQLite / Postgres)"]
    end

    git[("🌳 git repo<br/>tags = versions")]

    vmn <--> git
    cli -- "claims runs, writes<br/>code objects + logs" --> store
    sdk -- "metrics · params ·<br/>artifacts · run state" --> store
    ui -- "reads (and metadata edits)" --> store
    people(["👩‍🔬 People / AI agents"]) --> cli
    people --> ui

    classDef core fill:#e8f1ff,stroke:#3b6fd8,color:#0b2a66
    classDef exp fill:#efe7ff,stroke:#7a4fd8,color:#2a0b66
    classDef sdkc fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    classDef uic fill:#fff3e0,stroke:#e08a1e,color:#663a00
    classDef data fill:#f4f4f4,stroke:#666,color:#222
    class vmn core
    class cli exp
    class sdk sdkc
    class ui uic
    class store,git data
```

| Piece | Install | What it does |
|---|---|---|
| **vmn** | `pip install vmn` | Versioning in git tags. Knows nothing about experiments; provides `vmn snapshot` and the public `version_stamp.api` that vmn-exp builds on. |
| **vmn-exp-sdk** | `pip install vmn-exp-sdk` | The job-side writer: `start_run()`, logging, autolog, readers, the model registry, every storage backend. Needs neither git nor vmn. |
| **vmn-exp** | `pip install "vmn-exp[ui]"` | The platform: the `vmn-exp` command, git-mode capture, the MLflow importer and the `vmn-exp ui` dashboard. Pulls in the other two. |
| **Store** | a directory or a bucket | Plain files: runs, code, sweeps, registry, reports, a change journal. See [Inside the store](#inside-the-store). |

---

## Three packages, one store

The import rules are enforced by tests
(`packages/vmn-exp/tests/test_packaging_split.py`), so the SDK stays small
enough for a job image and vmn-exp can move to its own repository. Details:
[packaging.md](../packaging.md).

```mermaid
flowchart TB
    subgraph P1["📦 vmn  —  import package <code>version_stamp</code>"]
        api["<code>version_stamp.api</code><br/><i>public, versioned contract</i>"]
        vcore["stamp · release · goto · snapshot<br/>backends · conf · locks"]
        plug["plugin hooks<br/><code>vmn.plugins</code> entry point"]
        api --- vcore
        vcore --- plug
    end

    subgraph P3["📦 vmn-exp  —  <code>vmn_exp.cli · ui · snapshot · importers · gitmode</code>"]
        ecli["<code>vmn-exp</code> CLI<br/>supervisor · sweeps · push · rerun"]
        eui["<code>vmn-exp ui</code><br/>FastAPI + React web app"]
        gm["<code>gitmode</code><br/>cold start · snapshot capture"]
        imp["importers<br/>MLflow"]
    end

    subgraph P2["📦 vmn-exp-sdk  —  <code>vmn_exp.sdk · core · storage · registry · integrations · _base</code>"]
        s["<code>sdk</code><br/>start_run · Run · reader · autolog"]
        c["<code>core</code><br/>fold · index · query · status · lineage"]
        st["<code>storage</code><br/>local · S3 · GCS · Azure · journal"]
        r["<code>registry</code><br/>models + datasets"]
        s --> c --> st
        s --> r --> st
    end

    ecli -- "only via" --> api
    gm -- "only via" --> api
    plug -. "registers <code>vmn goto</code> of dev versions<br/>+ remote snapshot stores" .-> ecli
    ecli --> s
    eui --> c
    imp --> st
    s -. "lazy import, git mode only" .-> gm

    store[("🗄️ Store")]
    st <--> store

    classDef core fill:#e8f1ff,stroke:#3b6fd8,color:#0b2a66
    classDef exp fill:#efe7ff,stroke:#7a4fd8,color:#2a0b66
    classDef sdkc fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    classDef data fill:#f4f4f4,stroke:#666,color:#222
    class api,vcore,plug core
    class ecli,eui,gm,imp exp
    class s,c,st,r sdkc
    class store data
```

- `version_stamp` never imports `vmn_exp`. vmn finds vmn-exp only through the
  `vmn.plugins` entry point, which adds `vmn goto` of dev versions and remote
  stores for `vmn snapshot`.
- The SDK imports neither `version_stamp` nor the vmn-exp subpackages. The
  only exception is a lazy `vmn_exp.gitmode` import, used when `start_run()`
  must snapshot a git checkout. Without vmn-exp installed that path fails with
  "install vmn-exp for git mode", and git-free runs work as usual.
- vmn-exp reaches vmn only through `version_stamp.api`.
- `vmn_exp` is a namespace package split across vmn-exp-sdk and vmn-exp, so
  both install into the same `vmn_exp` import name.

---

## How clients use it

The same store serves every way of running. Pick the row that matches where
your jobs run. [client-guide.md](client-guide.md) walks through each one.

```mermaid
flowchart LR
    subgraph A["① Laptop / workstation"]
        a1["<code>vmn-exp run my_app -- python train.py</code><br/>or <code>start_run()</code> in a notebook"]
    end
    subgraph B["② Cluster with a checkout (Slurm, VMs)"]
        b1["<code>vmn-exp sweep agent</code> × N<br/>or a <code>submit.sh</code> wrapped in <code>vmn-exp run</code>"]
    end
    subgraph C["③ Pods without git (Kubernetes)"]
        c0["once, on a checkout:<br/><code>vmn-exp export -v &lt;outer&gt; -o ./code</code>"]
        c1["image: <code>vmn-exp</code> or <code>vmn-exp-sdk</code> + ./code<br/>env <code>VMN_SNAPSHOT_METADATA</code><br/><code>VMN_EXPERIMENT_STORE</code> · <code>VMN_EXPERIMENT_ID</code>"]
        c0 -- "bake into image" --> c1
    end
    subgraph D["④ Air-gapped nodes"]
        d1["<code>VMN_EXP_OFFLINE=1</code><br/>record to local disk"]
        d2["later, from a login node:<br/><code>vmn-exp push my_app</code>"]
        d1 --> d2
    end

    local[("<code>.vmn/store/</code><br/>in the checkout")]
    shared[("shared store<br/><code>file:///mnt/fsx</code> · <code>s3://team/ml</code>")]

    a1 --> local
    a1 -. "conf <code>experiment.storage.uri</code>" .-> shared
    b1 --> shared
    c1 --> shared
    d2 --> shared

    shared --> ui["📊 <code>vmn-exp ui --store &lt;uri&gt;</code><br/>one user, or a team server"]
    local --> ui2["📊 <code>vmn-exp ui</code><br/>in the checkout"]
    shared --> cli["⌨️ <code>vmn-exp list · compare · similar</code><br/><code>restore · rerun · vmn goto</code>"]

    classDef mode fill:#efe7ff,stroke:#7a4fd8,color:#2a0b66
    classDef data fill:#f4f4f4,stroke:#666,color:#222
    classDef uic fill:#fff3e0,stroke:#e08a1e,color:#663a00
    class a1,b1,c0,c1,d1,d2 mode
    class local,shared data
    class ui,ui2,cli uic
```

Where runs go is resolved the same way everywhere (CLI, SDK, `vmn snapshot`):
`--store` > `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri` > the
checkout's `.vmn/store/`. `VMN_EXP_OFFLINE` drops the remote store in all of
them.

### The loop a client goes through

```mermaid
flowchart LR
    edit["✏️ edit code<br/>(uncommitted is fine)"] --> run["▶️ run<br/><code>vmn-exp run</code> / <code>start_run()</code>"]
    run --> watch["👀 watch<br/><code>vmn-exp ui</code> · <code>list</code> · <code>watch</code>"]
    watch --> compare["⚖️ compare<br/><code>compare</code> · <code>diff</code> · <code>importance</code> · <code>similar</code>"]
    compare --> reproduce["♻️ reproduce<br/><code>restore</code> · <code>vmn goto -v</code> · <code>rerun</code>"]
    compare --> ship["🚀 ship<br/><code>vmn-exp model register</code><br/><code>vmn stamp</code>"]
    reproduce --> edit
    watch -. "diverged? " .-> fix["⏪ <code>rewind</code> / fork<br/>resume via SDK <code>run_id=</code>"]
    fix --> run

    classDef step fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    class edit,run,watch,compare,reproduce,ship,fix step
```

---

## The life of a run

What `vmn-exp run my_app -- python train.py` does. The repo lock is held only
while the run is created, so a long run never blocks other `vmn` commands, and
the child can open nested runs of its own.

```mermaid
sequenceDiagram
    autonumber
    actor U as You
    participant X as vmn-exp run<br/>(supervisor)
    participant V as vmn<br/>(version_stamp.api)
    participant S as Store
    participant J as python train.py<br/>(+ SDK)

    U->>X: vmn-exp run my_app -- python train.py
    rect rgb(232, 241, 255)
    note over X,V: repo lock held
    X->>V: auto-init + stamp 0.0.0 if the app is new
    X->>V: capture the code state<br/>(base commit, diff, untracked files)
    V-->>X: dev verstr 1.6.0-dev.a1b2c3d.e4f5g6h
    X->>S: code/: store the code object once per code identity
    X->>S: runs/: claim the run (atomic create_exclusive)
    end
    note over X: lock released
    X->>J: spawn with VMN_EXPERIMENT_ID,<br/>VMN_METRICS_FILE, VMN_APP_NAME
    par while the child lives
        J-->>X: stdout/stderr (tee'd to outputs/output.log)
        J-->>X: key=value lines in $VMN_METRICS_FILE
        J->>S: (optional) start_run() opens an inner run under VMN_EXPERIMENT_ID
        X->>S: heartbeat run_state.yml + sys_* metrics (every 30s)
        X->>S: ship new log lines / metric segments
    end
    J-->>X: exit code
    X->>S: final run_state.yml (exit_code), compact metrics, upload output.log
    X-->>U: exits with the child's exit code
```

Status is derived from `run_state.yml`, never stored: `running` while the
heartbeat is fresh, `succeeded`/`failed` from the exit code, and `stuck` when
the heartbeat goes stale with no exit code (a node that vanished).

```mermaid
stateDiagram-v2
    direction LR
    [*] --> created: claimed
    created --> running: heartbeat
    running --> succeeded: exit 0
    running --> failed: exit ≠ 0 / signal
    running --> stuck: heartbeat stale,<br/>no exit code
    stuck --> running: heartbeat resumes
    stuck --> failed: exit code written
    succeeded --> [*]
    failed --> [*]
```

---

## Outer runs and inner runs

A run created while `VMN_EXPERIMENT_ID` is set becomes an inner run of that
run, so nesting falls out of how you launch jobs. An outer run's
`tree_status` rolls up its subtree (`failed > stuck > running > created >
succeeded`).

```mermaid
flowchart TB
    outer["🧪 <b>outer run</b>  lr-sweep<br/><code>vmn-exp run my_app -- ./submit.sh</code><br/>tree_status: <b>failed</b>"]
    t1["inner · lr=1e-4<br/>✅ succeeded"]
    t2["inner · lr=3e-4<br/>✅ succeeded"]
    t3["inner · lr=1e-3<br/>❌ failed"]
    sdk1["inner · SDK start_run()<br/>✅ succeeded"]
    outer --> t1 & t2 & t3
    t2 --> sdk1

    code[("one code object<br/>shared by every run<br/>of the same tree")]
    t1 -.-> code
    t2 -.-> code
    t3 -.-> code
    outer -.-> code

    classDef outerc fill:#efe7ff,stroke:#7a4fd8,color:#2a0b66,stroke-width:2px
    classDef ok fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    classDef bad fill:#fdeaea,stroke:#d33,color:#600
    classDef data fill:#f4f4f4,stroke:#666,color:#222
    class outer outerc
    class t1,t2,sdk1 ok
    class t3 bad
    class code data
```

Sweeps work the same way: `vmn-exp sweep create` stores the spec on an outer
run, and each `vmn-exp sweep agent` claims trial slots and runs every trial as
an inner run ([sweeps.md](sweeps.md)).

---

## Inside the store

Every store root has the same areas, so a bucket policy is a list of prefixes
([byo-bucket.md](byo-bucket.md)). Records are append-only: a writer adds new
log segments and never rewrites another writer's files, which is why hosts
sharing a bucket or an NFS directory never collide.

```mermaid
flowchart LR
    root[("🗄️ store root")] --> marker["<code>store.yml</code><br/>layout: 2"]
    root --> runs["<code>runs/&lt;app-key&gt;/&lt;verstr&gt;/</code>"]
    root --> code["<code>code/&lt;app-key&gt;/</code><br/>patches + untracked tarball"]
    root --> snaps["<code>snapshots/</code><br/><code>vmn snapshot</code> records"]
    root --> sweeps["<code>sweeps/</code><br/>trial claims"]
    root --> reg["<code>registry/</code><br/>models + datasets"]
    root --> rep["<code>reports/</code> · <code>comments/</code>"]
    root --> jr["<code>journal/</code><br/>one empty object per change"]

    runs --> md["<code>metadata.yml</code><br/>name · parent · note · <code>code:</code>"]
    runs --> rs["<code>run_state.yml</code><br/>state · pid · heartbeat · exit_code"]
    runs --> lg["<code>log/&lt;writer&gt;~&lt;owner&gt;[@&lt;seq&gt;].jsonl</code><br/>params · notes · tags · artifacts"]
    runs --> mt["<code>metrics/</code><br/><code>.vms</code> while live → <code>.vmx</code> compacted"]
    runs --> out["<code>outputs/</code><br/>output.log · media/ · tables/"]
    runs --> art["<code>artifacts/</code><br/>your files"]
    md -. "code:" .-> code

    classDef data fill:#f4f4f4,stroke:#666,color:#222
    classDef area fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    classDef file fill:#ffffff,stroke:#999,color:#222
    class root data
    class marker,runs,code,snaps,sweeps,reg,rep,jr area
    class md,rs,lg,mt,out,art file
```

Per-host state (the index cache, the push ledger) lives outside the store, in
the XDG cache/state directories, so the store holds only shared, durable data.
Full layout: [experiments.md](experiments.md).

---

## How the dashboard reads the store

`vmn-exp ui` folds every run into one row (params, metric summaries, tags,
status) and keeps those rows in an index cache, so the leaderboard answers
from memory even at 100k runs. Logs, series, artifacts and code are read from
the store on demand. The cache can be deleted at any time and is rebuilt
from the store.

```mermaid
flowchart LR
    W1["SDK / vmn-exp run"] -- "1 write record" --> S[("🗄️ Store")]
    W1 -- "2 put journal entry" --> JR["journal/"]
    W2["push · import-mlflow ·<br/>registry · server edits"] --> S
    W2 --> JR

    subgraph UI["📊 vmn-exp ui"]
        direction TB
        RF["background refresher<br/>(once a second, watched apps only)"]
        IX[("index cache<br/>memory · SQLite · Postgres")]
        API["REST API<br/><code>/api/v1/...</code><br/>ETag · gzip · SSE events"]
        RF --> IX --> API
    end

    JR -- "list new entries" --> RF
    S -- "re-read changed records<br/>+ rolling consistency check" --> RF
    S -- "logs · series · media · code<br/>on demand" --> API
    API --> WEB["🌐 web app<br/>leaderboard · run page ·<br/>compare · charts"]
    API --> AG["🤖 scripts / agents"]

    classDef sdkc fill:#e6f7ee,stroke:#2e9e5b,color:#0b4026
    classDef uic fill:#fff3e0,stroke:#e08a1e,color:#663a00
    classDef data fill:#f4f4f4,stroke:#666,color:#222
    class W1,W2 sdkc
    class RF,API,WEB,AG uic
    class S,JR,IX data
```

- **Store workspaces** (`--store`) follow the change journal: each tick lists
  the journal's last two minutes (its whole 5-minute skew window every 30 s),
  then only the named records are re-read; a live run is re-listed for its
  heartbeat once per heartbeat interval (at least 10 s apart, at most half its
  stuck window), since heartbeats are not journaled.
- **Git workspaces** (`--repo`) have no journal and are refreshed by listing.
- **As a team server** (`--config server.yml`), the same process adds sign-in,
  API tokens, roles and an optional Postgres cache shared by replicas
  ([server.md](server.md)). Jobs still write only to the store.

See [ui.md](ui.md) for the flags and the HTTP API.

### CLI and SDK reads: the per-host index

`vmn-exp list`, `show`, `compare`, `similar`, ref resolution and the SDK
readers go through the same kind of cache: one SQLite file per app per store
on each host, outside the store. A refresh lists record names plus whatever
changed, and resolving one run is a point read, so thousands of runs stay
cheap. The file also holds each run's similar-runs document in an FTS5
table, which `vmn-exp similar` and the query language's `similar("<text>")`
search.

```mermaid
flowchart LR
    S[("🗄️ Store")] -- "names listing +<br/>changed records only" --> IX
    subgraph host["💻 this host  —  <code>$XDG_CACHE_HOME/vmn-exp/index/&lt;store-id&gt;/</code>"]
        IX[("experiment index<br/>one SQLite file per app<br/>lean rows · side tables · FTS5")]
        IX --> L["<code>vmn-exp list · show · compare</code><br/><code>@N</code> / prefix refs"]
        IX --> SM["<code>vmn-exp similar</code><br/>query <code>similar(…)</code>"]
        IX --> RD["SDK readers<br/><code>list_runs · get_run</code>"]
    end

    classDef data fill:#f4f4f4,stroke:#666,color:#222
    classDef uic fill:#fff3e0,stroke:#e08a1e,color:#663a00
    class S,IX data
    class L,SM,RD uic
```

Deleting the file costs one rebuild, never data
([The experiment index](experiments.md#the-experiment-index-per-host-cache)).
