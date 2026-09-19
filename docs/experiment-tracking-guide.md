# vmn Experiment Tracking — Workflow Guide for Engineers

**vmn experiments = snapshot of your code + append-only log of metrics.**
No server, no database — just files on disk (or S3).

---

## What Is an Experiment?

```mermaid
block-beta
    columns 3
    block:exp:3
        columns 2
        A["1. CODE SNAPSHOT\n(committed + uncommitted)"] B["Your code at that exact moment\n(patches, not full copies)"]
        C["2. METRICS LOG\n(append-only JSONL)"] D["key=value pairs over time\nloss=0.34, acc=0.91, ..."]
        E["3. METADATA\n(YAML)"] F["who, when, which branch,\nbase version, notes"]
    end
    style exp fill:#f0f4ff,stroke:#1e4682
```

> **Stored in:** `.vmn/<app>/experiments/<verstr>/`
> **Format:** plain files — YAML + JSONL — no database

---

## Workflow 1: Single Developer

You're on your laptop. You have a git repo with vmn set up (`vmn stamp -r patch my_app`). You want to try different configs and track what happened.

```mermaid
flowchart TD
    subgraph laptop["Your Laptop"]
        code["Your code\n(committed + uncommitted)"]
        cmd["vmn exp create / vmn exp run"]
        subgraph store[".vmn/my_app/experiments/"]
            e1["1.0.0-dev.a1b/\nmetadata.yml\nlog.local.jsonl\npatches/"]
            e2["1.0.0-dev.a1b.r2/\n(same code = .r2 suffix)"]
        end
        code --> cmd --> store
    end
    style laptop fill:#f0f4ff,stroke:#1e4682
    style store fill:#fff,stroke:#aaa
```

### Option A: Manual Measurements

Tweak your config, run your test yourself, then record:

```sh
# Experiment 1: try batch=64
vmn exp create my_app --note "batch=64" \
    --metrics latency_ms=12.3 throughput=8100

# Experiment 2: try batch=128
vmn exp create my_app --note "batch=128" \
    --metrics latency_ms=15.1 throughput=9400

# Compare results
vmn exp list my_app --sort latency_ms
vmn exp diff my_app    # code diff + metric delta
```

Each experiment snapshots your entire working tree (committed + uncommitted). If the code hasn't changed between runs, vmn appends `.r2`, `.r3`, etc. Nothing is overwritten.

### Option B: Let vmn Run Your Command

```sh
vmn exp run my_app --note "lr=0.01" -- python train.py --lr 0.01
```

What happens step by step:

1. Snapshots your working tree (committed + uncommitted)
2. Launches your command, streams output to your terminal
3. Sets `$VMN_METRICS_FILE` — your script writes key=value lines there
4. vmn tails that file live (metrics appear in the UI in real time)
5. When command exits, vmn records exit code + duration

### Writing Metrics From Your Script

```python
import os

metrics_file = os.environ["VMN_METRICS_FILE"]

def log_metric(key, value, step=None):
    with open(metrics_file, "a") as f:
        prefix = f"step={step} " if step is not None else ""
        f.write(f"{prefix}{key}={value}\n")

for epoch in range(100):
    log_metric("loss", loss, step=epoch)    # -> live training curve
log_metric("final_acc", acc)                 # -> scalar metric
```

> `step=N` gives you training curves in the UI. Without `step=`, you get scalar metrics. Works from any language — shell scripts can do: `echo "loss=0.34" >> $VMN_METRICS_FILE`

### Browsing & Comparing

```sh
vmn exp list my_app              # table of all experiments
vmn exp list my_app --sort loss  # sorted by a metric
vmn exp show my_app --latest     # full detail of most recent
vmn exp diff my_app              # code diff + metric delta
vmn exp restore my_app --latest  # checkout that code state
vmn ui                           # web dashboard with charts
```

---

## Workflow 2: Multi-Developer Team

Your team shares a repo. Multiple people run experiments at the same time. Everyone wants to see all results in one place.

> **Key idea:** shared NFS mount + per-writer log files = safe concurrent writes

```mermaid
flowchart BT
    subgraph nfs["Shared NFS / FSx Mount — /mnt/shared"]
        direction TB
        subgraph alice_exp["1.0.0-dev.abc.alice/"]
            a_meta["metadata.yml"]
            a_log["log.alice-laptop.jsonl"]
        end
        subgraph bob_exp["1.0.0-dev.abc.bob/"]
            b_meta["metadata.yml"]
            b_log["log.bob-desktop.jsonl"]
        end
        subgraph carol_exp["1.0.0-dev.def.carol/"]
            c_meta["metadata.yml"]
            c_log["log.carol-laptop.jsonl"]
        end
    end

    alice["Alice\nlaptop"] --> alice_exp
    bob["Bob\ndesktop"] --> bob_exp
    carol["Carol\nlaptop"] --> carol_exp

    style nfs fill:#f0f4ff,stroke:#1e4682
    style alice fill:#e8f5e9,stroke:#388e3c
    style bob fill:#fff3e0,stroke:#f57c00
    style carol fill:#fce4ec,stroke:#c62828
```

> Each person writes their **own** log file (no conflicts). When reading, vmn merges **all** `log.*.jsonl` files automatically.

### Setup: One-Time

Mount a shared filesystem that all team members can access. NFS, AWS FSx, GlusterFS, or any POSIX-compatible shared mount works.

### Each Developer's Workflow

```sh
# Set your writer ID (once, in .bashrc or .zshrc)
export VMN_WRITER_ID=$(hostname)    # or your name: alice-laptop

# Run experiments pointing to the shared mount
vmn exp run my_app \
    --experiment-dir /mnt/shared \
    --writer-id $VMN_WRITER_ID \
    --note "lr=0.01, batch=64" \
    -- python train.py --lr 0.01

# Or with manual metrics
vmn exp create my_app \
    --experiment-dir /mnt/shared \
    --metrics loss=0.34 acc=0.91 --note "new optimizer"
```

### Why This Is Safe for Concurrent Writes

1. **Writer ID** — each person gets a unique writer ID. Their metrics go to their own file: `log.alice-laptop.jsonl`. No file collisions.
2. **Unique verstr** — each experiment verstr includes the writer ID as suffix: `1.0.0-dev.abc.alice-laptop`. No version collisions.
3. **Atomic writes** — JSONL files use `O_APPEND`, which is atomic on POSIX for lines under 4KB. No locking needed.

### Viewing All Team Results

```sh
# Anyone on the team can see all experiments:
vmn exp list my_app --experiment-dir /mnt/shared
vmn exp diff my_app --experiment-dir /mnt/shared

# Or launch the web UI for a dashboard + charts:
vmn ui --repo /mnt/shared
```

> vmn merges all `log.*.jsonl` files sorted by timestamp — one unified leaderboard.

---

## Workflow 3: K8s at Scale

You're running a hyperparameter sweep: 100–1000 pods, each with a different config. No pod has git installed — they're running from an exported snapshot. Two sub-modes: shared NFS mount (simpler) or S3 (no shared filesystem needed).

### Mode A: K8s + Shared NFS / FSx

> Recommended when you already have a shared filesystem (EFS, FSx, NFS).

```mermaid
flowchart TD
    subgraph cp["Control Plane (your machine / CI)"]
        step1["1. vmn snapshot export my_app"]
        step2["2. tar xzf → /mnt/fsx/code/"]
        step3["3. kubectl apply -f sweep-job.yaml"]
        step1 --> step2 --> step3
    end

    step3 -- "shared NFS mount: /mnt/fsx" --> pod1 & pod2 & podN

    subgraph pod1["Pod 1 — lr=0.01"]
        p1_read["reads: vmn_metadata.yml"]
        p1_write["writes: log.pod1.jsonl"]
    end

    subgraph pod2["Pod 2 — lr=0.03"]
        p2_read["reads: vmn_metadata.yml"]
        p2_write["writes: log.pod2.jsonl"]
    end

    subgraph podN["Pod N — lr=0.1"]
        pN_read["reads: vmn_metadata.yml"]
        pN_write["writes: log.podN.jsonl"]
    end

    pod1 & pod2 & podN --> ui["vmn ui --repo /mnt/fsx\nLeaderboard + live curves"]

    style cp fill:#f0f4ff,stroke:#1e4682
    style pod1 fill:#e8f5e9,stroke:#388e3c
    style pod2 fill:#fff3e0,stroke:#f57c00
    style podN fill:#fce4ec,stroke:#c62828
    style ui fill:#fff9c4,stroke:#f9a825
```

> Each pod: **no git**, **no locks**, **no coordination**.

#### Step 1: Export a Snapshot (Control Plane)

```sh
# On your machine (has git)
vmn snapshot export my_app --latest -o /mnt/fsx/snapshot.tar.gz
tar xzf /mnt/fsx/snapshot.tar.gz -C /mnt/fsx/code/

# /mnt/fsx/code/ now contains:
#   vmn_metadata.yml   <- vmn reads this instead of git
#   your_code/         <- the actual source tree
```

#### Step 2: Each Pod's Entrypoint

```sh
vmn exp run my_app \
    --from-snapshot /mnt/fsx/code/vmn_metadata.yml \
    --experiment-dir /mnt/fsx \
    --writer-id $HOSTNAME \
    -- python train.py --lr $LR --batch $BATCH
```

#### What Each Flag Does

| Flag | What it does |
|------|-------------|
| `--from-snapshot` | Reads `vmn_metadata.yml` instead of git. No git needed. |
| `--experiment-dir` | Write to shared mount instead of local `.vmn/` |
| `--writer-id` | Unique pod ID. Metrics go to `log.<id>.jsonl` (no conflicts) |

The experiment verstr includes the pod ID: `1.0.0-dev.abc.def.pod-xyz-123`. Zero collision, zero contention, zero coordination between pods.

#### Step 3: View Results

```sh
# From your machine or a dashboard server:
vmn ui --repo /mnt/fsx

# CLI quick check:
vmn exp list my_app --experiment-dir /mnt/fsx --sort loss --top 10
```

### Mode B: K8s + S3 (No Shared Filesystem)

> Use this when pods don't share a filesystem — each writes locally and syncs to S3.

```mermaid
flowchart TD
    subgraph pod1["Pod 1"]
        p1["/tmp/exp\nlog.pod1.jsonl"]
    end
    subgraph pod2["Pod 2"]
        p2["/tmp/exp\nlog.pod2.jsonl"]
    end
    subgraph podN["Pod N"]
        pN["/tmp/exp\nlog.podN.jsonl"]
    end

    pod1 -- "sync every 30s" --> s3
    pod2 -- "sync every 30s" --> s3
    podN -- "sync every 30s" --> s3

    subgraph s3["S3 Bucket: my-experiments"]
        s3a["vmn-experiments/my_app/\n├── verstr.pod1/ log.pod1.jsonl\n├── verstr.pod2/ log.pod2.jsonl\n└── verstr.podN/ log.podN.jsonl"]
    end

    s3 --> ui["vmn ui --s3-bucket my-experiments\nLeaderboard + live curves"]

    style pod1 fill:#e8f5e9,stroke:#388e3c
    style pod2 fill:#fff3e0,stroke:#f57c00
    style podN fill:#fce4ec,stroke:#c62828
    style s3 fill:#e3f2fd,stroke:#1565c0
    style ui fill:#fff9c4,stroke:#f9a825
```

#### Step 1: Export Snapshot to S3 or Embed in Image

```sh
# Option A: Export to S3
vmn snapshot export my_app --latest -o snapshot.tar.gz
aws s3 cp snapshot.tar.gz s3://my-experiments/snapshots/

# Option B: Bake into Docker image (simpler)
# Dockerfile:
#   COPY snapshot/ /workspace/
#   RUN pip install vmn
```

#### Step 2: Each Pod's Entrypoint

```sh
vmn exp run my_app \
    --from-snapshot /workspace/vmn_metadata.yml \
    --experiment-dir /tmp/exp \
    --writer-id $HOSTNAME \
    --backend s3 --bucket my-experiments \
    --sync-interval 30 \
    -- python train.py --lr $LR
```

#### How S3 Sync Works

```mermaid
sequenceDiagram
    participant Pod
    participant Local as /tmp/exp
    participant S3 as S3 Bucket

    Pod->>Local: t=0s: Create experiment, launch train.py
    Note over Pod,Local: Metrics written to local JSONL

    loop Every 30 seconds
        Local->>S3: Upload log.pod1.jsonl (replaces previous)
        Note over S3: Near-live metrics in UI
    end

    Pod->>Local: t=end: train.py exits
    Local->>S3: FINAL sync: complete log uploaded
    Note over S3: Exit code + duration recorded. No metrics lost.
```

- **Near-live:** Metrics appear in the UI within 30 seconds of being written
- **No data loss:** Final sync happens on exit — nothing is lost even if it crashes mid-interval
- **Any S3:** Uses standard S3 PutObject — works with AWS, MinIO, LocalStack, R2

#### Step 3: View Results

```sh
vmn ui --s3-bucket my-experiments --s3-prefix vmn-experiments

# Same UI as local mode: leaderboard, training curves,
# side-by-side comparison, code diffs
```

---

## Choosing a Workflow

|  | Single Dev | Multi-Dev Team | K8s at Scale |
|--|-----------|--------------|--------------|
| Git needed? | Yes | Yes | No (snapshot) |
| Shared FS? | No | Optional (NFS/FSx) | Optional (NFS or S3) |
| Concurrent? | No | Yes | Yes (1000+ pods) |
| Writer ID? | Optional | Recommended | Required |
| S3 support? | Yes | Yes | Yes |
| Setup | None | Mount or S3 bucket | Snapshot export |

```mermaid
flowchart TD
    Q["How many people/pods\nrun experiments?"]
    Q --> |"Just me"| W1["Workflow 1\nSingle Developer"]
    Q --> |"2–10 people"| W2["Workflow 2\nMulti-Developer Team"]
    Q --> |"10+ pods"| W3["Workflow 3\nK8s at Scale"]

    W1 & W2 & W3 --> storage

    subgraph storage["Pick your storage (any workflow)"]
        local["LOCAL DISK\njust works, simplest"]
        nfs["NFS / FSx\nshared mount, multi-machine"]
        s3s["S3\nno shared FS needed"]
    end

    style W1 fill:#e8f5e9,stroke:#388e3c
    style W2 fill:#fff3e0,stroke:#f57c00
    style W3 fill:#fce4ec,stroke:#c62828
    style storage fill:#f0f4ff,stroke:#1e4682
```

> **Typical combos:** Single dev → local disk (default) · Multi-dev → NFS or S3 · K8s → NFS (recommended) or S3

---

## Reference: Addressing Experiments

Every command that takes an experiment reference supports these forms:

| Form | Meaning |
|------|---------|
| (omitted) | The latest experiment |
| `--latest` | Most recent, explicitly |
| `@N` | N-th row from `exp list` (1-indexed) |
| unique prefix | e.g. `-v 1.6.0-dev.a1b` (shortest unique match) |
| full verstr | Exact match |

---

## Reference: Environment Variables

### Variables You Set (pod spec / .bashrc)

| Variable | Purpose |
|----------|---------|
| `VMN_WRITER_ID` | Unique writer ID (or use `--writer-id` flag) |
| `VMN_EXPERIMENT_DIR` | Shared mount path (or use `--experiment-dir` flag) |
| `VMN_SNAPSHOT_METADATA` | Path to `vmn_metadata.yml` (or use `--from-snapshot`) |

### Variables Set BY vmn (for your training script)

| Variable | Purpose |
|----------|---------|
| `VMN_EXPERIMENT_ID` | The verstr assigned to this run |
| `VMN_APP_NAME` | The app name |
| `VMN_METRICS_FILE` | Path to write key=value metric lines |

---

## Reference: CLI Flags for Multi-User / K8s

| Flag | Description |
|------|-------------|
| `--from-snapshot <path>` | Path to `vmn_metadata.yml` (skips git) |
| `--experiment-dir <path>` | Write experiments to shared mount or scratch dir |
| `--writer-id <id>` | Unique writer ID for this pod/process |
| `--sync-interval <sec>` | Seconds between S3 metric syncs (default: 30) |
| `--backend s3` | Use S3 storage backend |
| `--bucket <name>` | S3 bucket name |
| `--endpoint-url <url>` | Custom S3 endpoint (MinIO, LocalStack) |
| `--prefix <prefix>` | Key prefix in bucket (default: `vmn-experiments`) |

---

## Quick Start: K8s Pod Spec (NFS)

```yaml
containers:
  - name: experiment
    image: my-training:latest
    command:
      - vmn
      - exp
      - run
      - my_app
      - --from-snapshot
      - /mnt/fsx/code/vmn_metadata.yml
      - --experiment-dir
      - /mnt/fsx
      - --writer-id
      - $(HOSTNAME)
      - --
      - python
      - train.py
    env:
      - name: HOSTNAME
        valueFrom:
          fieldRef:
            fieldPath: metadata.name
    volumeMounts:
      - name: shared
        mountPath: /mnt/fsx
volumes:
  - name: shared
    persistentVolumeClaim:
      claimName: fsx-experiments
```

## Quick Start: K8s Pod Spec (S3)

```yaml
containers:
  - name: experiment
    image: my-training:latest
    command:
      - vmn
      - exp
      - run
      - my_app
      - --from-snapshot
      - /workspace/vmn_metadata.yml
      - --experiment-dir
      - /tmp/exp
      - --writer-id
      - $(HOSTNAME)
      - --backend
      - s3
      - --bucket
      - my-experiments
      - --sync-interval
      - "30"
      - --
      - python
      - train.py
    env:
      - name: HOSTNAME
        valueFrom:
          fieldRef:
            fieldPath: metadata.name
      - name: AWS_DEFAULT_REGION
        value: us-east-1
    # No shared volume needed — S3 is the shared storage
```

---

## End-to-End Example: Hyperparameter Sweep

Here's the full lifecycle, from setup to viewing results:

**1. Stamp a base version (on your laptop, once):**

```sh
vmn stamp -r patch my_app
vmn snapshot export my_app --latest -o snapshot.tar.gz
```

**2. Upload to shared storage:**

```sh
# NFS: extract to the mount
tar xzf snapshot.tar.gz -C /mnt/fsx/code/

# S3: upload and bake into image
aws s3 cp snapshot.tar.gz s3://my-experiments/snapshots/
```

**3. Launch the sweep:**

Your Kubernetes Job template runs `vmn exp run` per pod (see pod specs above).

**4. Watch live results:**

```sh
vmn ui --repo /mnt/fsx           # NFS mode
vmn ui --s3-bucket my-experiments # S3 mode

# Open http://localhost:8265 — leaderboard + training curves
```

**5. Pick the winner:**

```sh
vmn exp list my_app --experiment-dir /mnt/fsx --sort loss --top 5
vmn exp show my_app -v <best-verstr> --experiment-dir /mnt/fsx
vmn exp restore my_app -v <best-verstr>  # checkout that code
```
