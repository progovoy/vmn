# Reports and comments

A report is a markdown document with live charts embedded in it. A comment
thread can hang off a run or a report. Both are plain records in the store,
like runs. They have no database: they survive a cache drop, are picked up
through the change journal ([server.md](server.md#how-the-cache-stays-fresh)),
and can be read and written without a server through the CLI.

## Storage layout

```
reports/<rid>/
  header/                  metadata.yml {type: report_header, created_at, created_by}
                           log/<writer>.jsonl: title / archived / pinned / published changes
  v<N>/                    revision N (immutable)
    metadata.yml           {type: report_revision, base: N-1, author, created_at, message}
    report.md              the body
    data/<panel-id>.json   published revisions only: each panel's frozen data
    data/index.json        published panel ids (written after the panels)
  comments/                the report's comment thread
comments/<app-key>/<verstr>/   a run's comment thread (same key as the run in runs/)
```

- `<rid>` is `r` followed by 12 random lowercase base32 characters. Reports are
  found by id. Titles can change and need not be unique.
- Header changes are log entries, folded last-writer-wins.
- Records carry `format_version`. Readers skip records with a newer format.
- Deleting a report deletes its whole `reports/<rid>/` prefix, including its
  comments. `vmn-exp prune` deletes the comment threads of the runs it
  deletes.

## Revisions and conflicts

A save writes revision `base + 1`, where `base` is the revision the editor
started from. The revision is claimed with an atomic create-if-absent, so two
racing saves cannot both win. The loser gets the newer revision back:

```
POST /api/v1/workspaces/{ws}/reports/{rid}/revisions {"base": 3, "body": "...", "message": "..."}
  201 {"rev": 4}
  409 {"rev": 4, "body": "<their body>", "author": {...}}
```

On a `409`, the editor shows base, theirs and yours. When the edits don't
overlap it merges them line by line. Otherwise it offers a per-chunk choice
(theirs, yours, both, base). The editor also autosaves the draft to
localStorage (`vmn_report_draft:<ws>/<rid>`). **Save** (Ctrl+S) writes a
revision with an optional message. **History** lists the revisions (author,
time, message) and diffs any two of them.

The latest revision is the highest `v<N>` that exists.

## Panels: `vmn-panel` blocks

A panel is a fenced code block of YAML in `report.md`:

````markdown
## Learning-rate sweep

Cosine wins once warmup is at least 500 steps.

```vmn-panel
v: 1
id: p7k2
type: curves
app: trainer
runs: {query: 'params.sched = "cosine" and status = succeeded', limit: 20}
keys: [val_loss]
x: {mode: step}
smoothing: 0.6
log_y: true
```
````

Common fields:

| Field | Meaning |
|---|---|
| `v` | spec version, `1` (required) |
| `id` | stable id within the report, used for published data and anchors (required) |
| `type` | one of the types below (required) |
| `app` | app name in the report's workspace (required) |
| `runs` | pinned `{verstrs: [...]}`, or a live `{query, sort, order: asc\|desc, limit, archived}` using the [query language](sdk.md) (required) |
| `title`, `height` | optional display |

Types (`*` = single-run types, which take pinned `runs` only):

| `type` | Fields (required in bold) |
|---|---|
| `curves` | **`keys`**, `x: {mode: step\|wall\|relative\|metric, metric}`, `smoothing` (0-1), `log_y`, `max_points` |
| `leaderboard` | `columns`, `params` |
| `bar` | **`metric`** |
| `scatter` | **`x`**, **`y`** |
| `parallel` | **`columns`** |
| `importance` | **`metric`** |
| `grouped` | **`group_by`**, **`metric`** |
| `media`* | **`key`**, `step` (integer or `last`) |
| `table`* | **`path`** |
| `histogram`* | **`key`** |
| `lineage`* | `depth` |
| `run`* | none |

A panel with a bad spec renders as an error box. The rest of the report still
renders. You don't have to write blocks by hand: the editor's insert-panel
dialog writes them, and **Add to report** on the run page, the overlay and the
leaderboard charts appends the current view to an existing or new report.

Markdown rendering allows no raw HTML. Links open with
`rel="noopener noreferrer"`, and images may only point at workspace media
(`vmn://` refs).

## Live vs published

- **Live:** panels query current data each time they are viewed. A `query`
  panel picks up new runs.
- **Publish** (editor role) freezes a revision. The browser sends the data
  each panel rendered. The server checks it (at most 2 MB per panel and 50 MB
  per revision, and every run it names must exist), writes it to
  `v<N>/data/<panel-id>.json`, and only then appends `published` to the
  header, so readers never see partial data.
- Viewers see the published revision by default, with a "published <date> —
  view live" banner. Editors see the latest revision. `?live=1` forces live
  panels. Published panels render from `data/` and never query, so they stay
  the same after runs are pruned.

## HTML export

```sh
vmn-exp report export <rid> [--rev N] [-o report.html] [--max-media-mb 20]
```

This writes one self-contained HTML file: the rendered markdown, the published
panel data inlined as JSON, and a bundled renderer. Media is inlined as data
URIs up to `--max-media-mb`, and anything skipped is listed on stderr. The
default revision is the published one, else the latest. An unpublished
revision exports with empty panels and a warning. The file opens offline.

## CLI

All report and comment commands are git-free and work on the store directly,
with the storage flags of `vmn-exp model`: `--dir`, `--store`, `--bucket`,
`--prefix`, `--endpoint-url`, or the usual environment.

| Command | Does |
|---|---|
| `vmn-exp report list [--archived] [--json]` | `<rid>  v<N>  <title>` per report |
| `vmn-exp report show <rid> [--json]` | the latest revision |
| `vmn-exp report put --new -f body.md [--title T]` | create a report (title defaults to the first `# ` heading, else the file name) |
| `vmn-exp report put <rid> -f body.md [-m msg]` | save the next revision. A concurrent save makes it exit 1, so retry |
| `vmn-exp report export <rid> ...` | see above |
| `vmn-exp report delete <rid>` | delete the report, its revisions and comments |
| `vmn-exp comment <app> -v <ref> "text"` | comment on a run and print the comment id |
| `vmn-exp comments <app> -v <ref>` | print a run's thread: `<id>  <ts>  <author>[ (reply to <id>)]: <text>` |

## Comments

A thread's first comment claims the thread record. Every comment, edit,
resolve or delete appends an entry to the writer's log, and the thread folds
per comment id, last writer wins. A delete leaves a tombstone, so replies
stay attached. A comment can reply to another (`reply_to`) and carry an
`anchor`, for example `{panel: "<panel-id>"}` in a report or
`{metric: "loss", step: 1200}` on a run.

Server API (`target` is `run:<app>:<verstr>` or `report:<rid>`):

```
GET    /api/v1/workspaces/{ws}/comments?target=...                        viewer
POST   /api/v1/workspaces/{ws}/comments {"target", "text", "reply_to"?, "anchor"?}   editor
PATCH  /api/v1/workspaces/{ws}/comments/{target}/{id} {"text"?, "resolved"?}         editor
DELETE /api/v1/workspaces/{ws}/comments/{target}/{id}                                editor
```

**Author identity.** Through a server, the author is the signed-in principal,
and only the author or an admin may edit, resolve or delete a comment. Without
a server, the author is the writer's identity (writer id, git `user.email`, OS
user). Anyone who can write the store can append entries, as with any file in
it. The server's report index keeps per-run comment counts (total and
unresolved) for the leaderboard.

## Report API

All under `/api/v1/workspaces/{ws}`. Writes need `editor`, except delete
(`admin`), and are refused with `403` on a `--read-only` server.

```
GET    /reports[?archived=true]                list
POST   /reports {"title", "body"}              create -> {"rid", "rev": 1}
GET    /reports/{rid}                          header + latest revision
GET    /reports/{rid}/revisions/{n}            one revision
GET    /reports/{rid}/revisions/{n}/data/{panel}   published panel data
POST   /reports/{rid}/revisions                save (409 on conflict, see above)
POST   /reports/{rid}/publish {"rev", "data": {panel-id: payload}}
PATCH  /reports/{rid} {"title"?, "archived"?, "pinned"?}
DELETE /reports/{rid}
GET    /apps/{app}/reports[?verstr=]           reports whose panels show this app (or run)
```

On store workspaces, these writes need the server's identity to be able to
write `reports/` and `comments/` ([byo-bucket.md](byo-bucket.md)).
