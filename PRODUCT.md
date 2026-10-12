# Product

<!-- impeccable:product-schema 1 -->

Scope: vmn-exp and its web dashboard (`vmn-exp ui`, source in `packages/vmn-exp/webui`). Core vmn (versioning, `vmn stamp`/`goto`) appears here only where the dashboard surfaces it: versions, the stamp tree, code restore.

## Platform

web

## Users

- **Solo ML engineers and researchers** run `vmn-exp ui` on their own machine or devbox. They use it to compare runs, read training curves, inspect a run's code diff, params and artifacts, and find the run worth restoring or rerunning.
- **ML teams** share one `vmn-exp ui` process as a central server (SSO/OIDC, API tokens, roles, reports, comments) over a bucket they own.
- Both are primary. The team server grows out of the local dashboard and must never make the single-user case worse.
- **Secondary: AI agents orchestrating fleets of jobs.** Agents write runs through the SDK/CLI (`docs/vmn-exp/ai-fleet-tracking.md`, `vmn-exp skill`). People review that fleet's progress and results in the dashboard.

## Product Purpose

Local-first experiment tracking built on vmn. Every run is a snapshot of the code plus an append-only log of metrics and notes, kept as plain files in the repo or an object store (S3, GCS, Azure, `file://`). The dashboard lets people see which run did what, why, and from which exact code, and then get back to that state. Success: any result on screen can be traced to its code and reproduced (`restore`, `goto`, `rerun`) without a database or vendor in the loop.

## Positioning

Every run is a reproducible snapshot of your code in plain git tags and files you own. It is local-first: no server or database is required, and any run can be restored or rerun exactly. The team tier is bring-your-own-bucket SaaS. The hosted control plane never holds the data, jobs write straight to storage and never talk to the server, and the server's database is a throwaway cache rebuilt from storage. Training is unaffected when the server is down.

## Operating Context

- Started with `vmn-exp ui` (default `127.0.0.1:8265`, opens a browser) from inside a checkout, or with `--repo`/`--store`/`--config` from anywhere. A workspace is either a git checkout or a read-only store URI.
- Users move between the dashboard and the terminal: `vmn-exp run/list/show/compare/restore/rerun`, `vmn goto`, and the SDK in training scripts. UI mutations run as real `vmn`/`vmn-exp` subprocesses.
- Watched apps can be large: the UI is built to stay fast at ~100k runs (paged, server-sorted lists, ETag/304, downsampled series).
- Live runs heartbeat while users watch. Status (`created`/`running`/`stuck`/`succeeded`/`failed`) is derived, never stored.
- Read-only deployments (`--read-only`, store workspaces) are normal, so many views have no edit affordances.

## Capabilities and Constraints

- Surfaces (routes): workspaces home, apps, experiments leaderboard (query language `?q=`, saved views, column picker, charts, parameter importance, similar mode), run detail (metrics, curves, media/tables/histograms, artifacts, lineage, provenance, sweep, fork/rerun info, notes, comments), code diff, compare runs, curve overlay, stamp tree, actions, model/dataset registry, reports (view/edit, `vmn-panel` blocks, HTML export), API tokens.
- Terminology to keep exactly: workspace, app, run/experiment, verstr, `@N`, outer/inner/single run, sweep/trial, snapshot, code object, stamp, model/dataset version, alias, report, panel.
- Security model is part of the product: token-gated `/api`, DNS-rebinding guard, Origin checks on mutations.
- `vmn-exp` will become a separate product from core vmn. Its docs live under `docs/vmn-exp/`.
- Undecided: per the 2026-08 UX review, the stamp tree / version overview should become the primary landing page, but the dashboard still opens on workspaces/leaderboard.

## Brand Commitments

- Names: `vmn` (core), `vmn-exp` (experiments product and command), `vmn-exp-sdk` (job-side package).
- Voice: terse, precise and technical, the voice of the CLI. Output is concise and pipe-friendly, with no chatty summaries. UI copy uses the same nouns as the CLI and docs.

## Evidence on Hand

- Docs: `docs/vmn-exp/` (client guide, experiments, SDK, UI, server, BYO bucket, models, sweeps, reports, MLflow comparison and migration), `packages/vmn-exp/examples/`, `demo/`.
- Real comparison material: `docs/vmn-exp/vmn-vs-mlflow.md`, `docs/vmn-exp/migrating-from-mlflow.md`.
- Missing, so never fabricate: customer logos, testimonials, user counts, benchmarks beyond those in the docs, SaaS pricing, hosted-service availability claims.

## Product Principles

1. **Storage is the truth.** Everything the UI shows comes from files the user owns, and every cache is disposable. Never design a view that implies data lives in the server.
2. **Every number traces to code.** A metric, curve or model on screen should lead back to the run, its code diff, and the way to restore or rerun it.
3. **Solo first, team-ready.** Team features (sharing, reports, roles) layer on the local dashboard without adding setup or friction for one person on localhost.
4. **Scale is the normal case.** Thousands to 100k runs and live fleets of jobs are expected, so views must stay scannable and fast at that size.
5. **Same words as the CLI.** The UI is another window onto the CLI's model and must never rename or hide its concepts.

## Accessibility & Inclusion

Best effort; no formal standard has been adopted. The dashboard ships dark and light themes (system-following by default).
