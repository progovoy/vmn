# Plan 19: the vmn-native dashboard shell

> The `vmn-exp ui` shell (sidebar, topbar, ⌘K, not-found, sign-in, home) is generic.
> It shows a hardcoded pulsing `local` chip, nav items that move between routes, a raw
> router 404, and a `window.prompt` token gate. This plan fixes every item in
> `.impeccable/critique/2026-10-12T07-12-46Z__packages-vmn-exp-webui-src-app-tsx.md`
> (score 22/40) and makes the frame show what vmn knows: the workspace, `branch @ HEAD`,
> dirty, the store, who you are, and whether you can write. It also adds CLI grammar
> (`@54`, `show -v`, `compare @3 @7`, `goto`).
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`) or `docs/`.

Status: **proposal** (2026-10-12). Three proposals were merged into this plan: terminal,
provenance and operate. §1 records the decisions, §2 the contracts, §3 the work units,
§4 the integration and verification steps. Revised after an adversarial review (2026-10-12) against the code at `fd20fbc4`: the facts it rests on are in §0.

The visual world stays: the warm near-black palette (`styles.css:1-85`), IBM Plex, and
the release-mode colours. This is a refinement, not a rebrand.

## 0. Ground truth (verified against `fd20fbc4`)

| Fact | Where |
|---|---|
| `/meta` returns only `{version, read_only}`. `version` is core vmn's (`version_stamp.api.version`) | `ui/server.py` `meta()` |
| `/workspaces` returns `to_public_dict()`: `name, kind, path?, store?, downloads?, reconcile_sec?, capabilities?, disconnected_at?` | `ui/workspaces.py:30-45` |
| `/apps` returns `{name, experiments, versions}` from a 5 s `TTLCache` (`app_lists`, `APPS_TTL_SEC`). An unknown app is not a 404: lists come back empty | `ui/server.py` `list_apps` |
| The 401 body is `{"detail":"Unauthorized"}`, sent from the `_authenticate` middleware for `/api*` | `ui/server.py` |
| The chain is `AuthenticatorChain.authenticators`. OIDC authenticators have `.router()`. A static token is a `StaticTokenAuthenticator` whose principal id is `"static-token"`. With a control plane, an `ApiTokenAuthenticator` is appended | `ui/auth/__init__.py`, `ui/auth/static.py`, `ui/server.py` |
| `effective_role(principal, workspace, mappings)` returns `viewer\|editor\|admin\|None` | `ui/auth/authz.py` |
| `app.state.config` is set only by `server_app` (`--config`). `app.state.control_plane` is set by `create_app` | `ui/cli.py`, `ui/server.py` |
| No git branch, HEAD or dirty endpoint exists. The only git subprocess precedent is `tree_cache.versions_fingerprint` | `ui/tree_cache.py` |
| The facets payload is `{branches, metric_keys, param_keys, total}`: no status counts | `ui/leaderboard_facets.py` |
| `LeaderboardCache.ordered(snapshot, schema)` returns the non-archived rows with derived status. `etag(snapshot, schema, **params)` changes with each generation and each live time bucket | `ui/leaderboard_cache.py` |
| Run detail resolves `@N`, prefix and `latest`. `detail_options` already passes `read_child_row=snap.row` but the payload carries no `idx` or `name`. The 404 text is `Experiment X not found` | `ui/readers/experiment_detail.py`, `ui/experiment_source.py:189-203` |
| `server.py` is 601 lines, so new routes go in new `routes_*.py` modules (the `register(app, prefix, …)` pattern) | `ui/server.py` |
| vmn-exp has its own version (0.1.4, `packages/vmn-exp/pyproject.toml:7`) | |
| The shell problems: `App.tsx` (220 lines) shows a hardcoded `● local`, wordmark `vmn ui`, a shared `default` icon, nav order Models → Reports → Tokens → Experiments, and a docs link to the repo root. `routes.tsx` has no `errorElement`, no `*` route, and a blank `PageFallback`. `http.ts` uses `window.prompt` in `get` only. `index.html` loads Google Fonts and has `<title>vmn</title>` | |
| Light-mode pills: good `#1c8560` is 4.02:1 on `--light-panel-2`, bad 4.45, stuck 3.67 on its 12% tint | `styles.css:52-57, 378-393` |
| URL params the palette targets: leaderboard `q`, `status`, `archived`, `new`, `sort`, `order`; `compare?v=&to=`; `compare-runs?sel=` (repeated); `overlay?runs=a,b`; `tree?v=` | `hooks/useLeaderboardView.ts`, pages |
| `/tokens` and `POST /workspaces` require `admin` in `*` (`require(ADMIN)` on a route without `ws_name`): a per-workspace admin gets 403 | `ui/routes_admin.py`, `ui/server.py` |
| With auth on, a principal that holds only per-workspace roles has `effective_role(p, None) is None`. So `role: null` alone cannot mean "auth off" | `ui/auth/authz.py` |
| `/auth/login`, `/auth/callback` (redirects to `/`) and `POST /auth/logout` live outside `/api`, so `post()` (which prefixes `/api/v1`) cannot call them, and the request guard does not apply | `ui/auth/oidc_routes.py`, `ui/security.py` |
| `LeaderboardCache.etag` uses the time bucket only while some row is live (`bucket` is `None` otherwise). A value that changes only with wall-clock time (a failure ageing out of a 24 h window) needs its own time component in the key | `ui/leaderboard_cache.py` `_base` |
| `git status` refreshes the index and may take `index.lock`, which races a concurrent `vmn stamp`. `GIT_OPTIONAL_LOCKS=0` prevents that | git docs |
| Page tests render under a plain `<MemoryRouter>` (48 files). `useMatches()` throws outside a data router, so **pages must never call `useShellContext`** | `pages/__tests__/*` |
| `.eyebrow` is used by about 30 in-page components (cards, run sections, reports). Only the shell's own surfaces drop it | `grep -rl eyebrow src` |
| UI copy that breaks the noun rule outside the shell: `LeaderboardToolbar.tsx:53` `+ New experiment`; `NewExperiment.tsx` (eyebrow `new experiment`, button `Create experiment`); `Compare.tsx:12,60` `two experiments` | |
| Existing tests pinned to old shell copy or props: `CommandPaletteSearch.test.tsx` and `fix_components.test.tsx` (palette props `ws/app/workspaces/apps`), `Leaderboard.test.tsx:110` (`No experiments yet`), `LeaderboardUrl.test.tsx:111` (`+ New experiment`), `AppShell.test.tsx` (`handle: {page}` fixtures, `.route-fallback`, `vmn 1.2.3`, `routes[0].children` flat paths), `Tokens.test.tsx:59` (`/no control plane/` on a 503) | |

**Noun rule.** The docs say "run(s)" for the recorded thing by a wide margin (ui.md: 93 against 47; experiments.md: 321 against 43). The product area is "Experiments" (experiments.md §1).

- **experiments** names the place: the sidebar item, the leaderboard crumb, and the command `vmn-exp`.
- **run** names rows, counts, empty states and palette rows. The UI never says "N experiments".
- API field names (`AppRow.experiments`) stay; only labels change.
- The CLI's own `No experiments found` (`cli/experiment.py`) is out of scope. It is flagged in §5.

**Mono rule.** Mono is only for real identifiers: verstr, `@N`, app, branch, sha, URI, and commands. Labels, headings and buttons stay in IBM Plex Sans. The craft floor bans monospace as a costume.

**Icon rule.** Every shell icon is an authored SVG from `components/shell/icons.tsx` (U0): 15×15 viewBox, `currentColor`, stroke 1.6, `aria-hidden="true"`, `focusable="false"`. No unicode glyph stands in for an icon anywhere in the shell: not `☰ ▾ › ‹ ↗ ✕ ◐ ☀ ☾`. Key names in the palette footer (`↑↓ ↵ ⇧ ⌘ esc`) are key labels, not icons, and stay text.

**Eyebrow rule.** No shell surface (NotFound, sign-in, home, apps, AddWorkspace, CacheResync, the New-run form) renders an eyebrow. The `.eyebrow` CSS rule stays for the in-page cards that still use it; that is flagged in §5.

**Test-change rule.** The existing tests listed in §0 change only where a binding user decision changes the behaviour they pin (the noun rule, the palette's new props, the route `handle` shape). The unit that makes the change edits those tests first, in its red step, and names each edited assertion in its commit message. No assertion is edited to turn a red test green after implementation. Any other existing test that turns red means stop and ask.

## 1. Decisions

### 1.1 Shell layout

```
<a.skip-link href="#main">Skip to content</a>
<ShellOverrideProvider>                                       (U0; lets NotFound / SignIn retitle the shell)
<div.shell>
  <aside.sidebar id="sidebar">                                drawer below 900px
    <div.drawer-context><ContextRoot/></div>                  shown only in the drawer (CSS)
    <Sidebar ctx footExtra={<ThemeToggle/>}/>                 footExtra shown only below 600px (CSS)
  </aside>
  <div.main-col>
    <header.topbar>  <Topbar/>  </header>
    <main#main.content tabIndex=-1>  <AuthGate><ErrorBoundary><Outlet/></ErrorBoundary></AuthGate>  </main>
  </div>
</div>
<CommandPalette/> (portal-free, sibling of .shell; .shell gets `inert` while open)
<div.sr-only aria-live="polite">{document title on route change}</div>
</ShellOverrideProvider>
```

**Shell override.** NotFound and SignIn render inside the page outlet, but the crumbs and `document.title` must read `not found` / `sign in`. U0's `shell/shellOverride.tsx` provides a context: `useOverrideRoute(id)` sets the override on mount and clears it on unmount, and `ShellContext.override` exposes it. The default context value is a no-op, so components that call it work under a plain `MemoryRouter` with no provider.

### 1.2 Sidebar: `components/shell/Sidebar.tsx`

The groups and their order are fixed. Items never move between routes. When an item does not apply it is **disabled with a reason**, never removed. The only exception is the Server group, which depends on how the server is deployed.

```
[v] vmn-exp                       wordmark: "vmn" --text, "-exp" --text-3; Link "/" state {home:true}
<div.nav-scope>                   no heading; the select's visible value names the workspace
  <label.sr-only for="ws-select">Workspace</label>  <select#ws-select>   options "ml-repo — git" / "team — store"
  /srv/checkouts/ml-repo [copy]   existing CopyPath (wsLocation)
APP                               <h2.nav-label>App</h2> + app switcher button "ml_app [chevron-down]" + <StatusRollup compact/>
  Experiments                     icon "experiments" (bars)
  Stamp tree                      icon "tree" (branch)
  Actions                         icon "actions" (prompt >_)
WORKSPACE                         <h2.nav-label>Workspace</h2>
  Apps                            icon "apps" (2x2 grid)         /ws/:ws (end)
  Models                          icon "models" (stacked layers) /ws/:ws/models
  Reports                         icon "reports" (ruled page)    /ws/:ws/reports
SERVER                            <h2.nav-label>Server</h2>; only when meta.control_plane
  API tokens                      icon "key"; shown when control_plane && (auth off || meta.role === "admin")
foot: <span>vmn-exp 0.1.4</span> · <span>vmn 0.10.2</span>   <a>Docs [external]<span.sr-only> (opens on GitHub)</span></a> → DOCS_URL
      {footExtra}
```

The order is App, then Workspace, then Server. Experiments comes first, as decided. The workspace **select** sits above the App group because it chooses scope: it is a control, not a nav group, so it has no `h2`. Its accessible name is `Workspace` (an `sr-only` label), and the selected option shows the name and kind. This avoids two visible "Workspace" headings. The three nav groups are each a `<nav aria-labelledby>` with their `<h2 class="nav-label">`. The foot renders the two versions as separate spans; `vmn-exp` is omitted when `meta.vmn_exp_version` is `null`.

**App group with no app in context** (on `/ws/:ws`, models, reports, or a global route): the switcher button reads `choose app` and opens the same menu of the workspace's apps. The three items still render, disabled with `choose an app first`. The App group never lists apps itself: per-app status lives on the Apps page tiles, which keeps the sidebar at one status request (the current app's).

Disabled items render as `<span class="nav-item" aria-disabled="true" title="…">`. They are not links. The `title` strings are exact:

- Stamp tree / Actions on a store workspace: `store workspace: no checkout`
- Actions when `meta.read_only`: `read-only server`
- Actions when the role is viewer: `your role in ml-repo is viewer`
- Actions when auth is on and the principal has no role in the workspace: `you have no role in ml-repo`
- App items with no app in context: `choose an app first`
- Workspace items with no workspace (none in the URL and no `lastWorkspace()`): `choose a workspace first`

**No workspace in the URL** (`/`, `/tokens`): the select and the App group use `lastWorkspace()` (§2.3), so `/tokens` keeps its context. If that is empty, the select shows the disabled option `workspace…`. An unknown `:ws` also shows `workspace…`, never the bogus name.

**Active state.** Experiments is active for the route ids `experiments`, `run`, `code-diff`, `compare-runs` and `overlay`. This comes from `ShellContext.routeId`, not NavLink `end`.

**App switcher.** A `<button aria-haspopup="menu" aria-expanded>` opens a `role="menu"` of the workspace's apps (`menuitem` links). Esc closes it and returns focus to the button. It reuses the `useDismiss` hook. The menu is `position: fixed` (anchored to the button's rect), so the sidebar's `overflow: auto` cannot clip it.

**Icons.** Seven distinct nav icons from `components/shell/icons.tsx` (U0, Icon rule in §0): `experiments | tree | actions | apps | models | reports | key`. They replace App.tsx's local `NavIcon` and its shared `default` icon.

**Select styling.** `#ws-select` gets `appearance: none`, the panel-2 surface, `--line-2` border, 32 px height, and a `chevron-down` icon element laid over its right edge (`pointer-events: none`, `--text-2`). It also gets the shared `:focus-visible` ring (in `Sidebar.css`).

### 1.3 Topbar: `components/shell/Topbar.tsx`

There is one row, 48 px high:

```
[menu icon]*  <nav aria-label="Breadcrumb"><ol> [ContextRoot] > crumb > … > leaf </ol></nav> [Copy as CLI]
      ── spacer ──  [read-only]  [Search ⌘K]  [ThemeToggle]  [IdentityChip]
* only below 900px
```

**ContextRoot** (`components/shell/ContextRoot.tsx`) is the first crumb and the "prompt". The workspace name is a link to `/ws/:ws`. The other segments are mono, `--text-2`:

| Workspace state | Text |
|---|---|
| git, on a branch, clean | `ml-repo  main @ e71c74d  · .vmn/store` |
| git, dirty | `ml-repo  main @ e71c74d  [dirty]  · .vmn/store` |
| git, detached | `ml-repo  detached @ e71c74d  · .vmn/store` |
| git context failed or loading | `ml-repo` (the segment is dropped silently) |
| git, `head` null (no commit yet) | `ml-repo  main @ (no commits)  · .vmn/store` |
| store | `team  store · s3://team-exp/ml` (middle-truncated; the full URI is in `title`). No git request is made |
| no workspace | (no ContextRoot; crumbs start at the leaf) |

- `[dirty]` is a bordered badge, `.ctx-dirty`, coloured `--hotfix`. Its text is `dirty` and its `title` is `uncommitted changes to tracked files. vmn snapshot create <app> saves them`.
- Below 1280 px, the store segment drops to `title`. Below 900 px, ContextRoot is hidden in the topbar and shown at the top of the drawer.
- ContextRoot is a link plus spans. There is no popover; copying the path is the sidebar CopyPath's job.

**Read-only badge**, `.ro-badge`, a bordered sans label `read-only`, shown when `ShellContext.readOnly`. Its `title` names the first reason that applies:

- `Started with --read-only: actions and edits are off`
- `Your role in ml-repo is viewer`
- `You have no role in ml-repo`
- `This store gives no edit access`

**IdentityChip** (`components/shell/IdentityChip.tsx`) replaces the pulsing `● local`. It never pulses.

| State | Chip | Menu (`aria-haspopup="menu"`) |
|---|---|---|
| `meta.auth.enabled` false, `location.hostname` loopback (`localhost`, `127.*`, `::1`) | `local`, title `vmn-exp ui on <host>: no sign-in` | none (plain `<span>`) |
| auth off, other host | `<location.host>`, title as above | none |
| principal `static-token` | `token · admin` | `Sign out` |
| OIDC or API token | `<principal.name> · <role>`, where role is the current workspace's `role`, else `meta.role`, else omitted | per-workspace roles (`ml-repo  editor`, `no role` for null), `Copy CLI login` (`vmn-exp login --server <origin>`), `Sign out` |
| `/meta` failed with 401 | `not signed in` (plain span; AuthGate shows the sign-in page) | none |
| `/meta` failed with 403 | `no access`, title = the server's `detail` | `Sign out` |
| `/meta` failed with no HTTP status (network) | `server unreachable` in `--bad` with the `close` icon, title `retrying…` | none |
| loading | nothing (no placeholder chip) | none |

`ShellContext.metaError` is true only in the network case. A 401 is AuthGate's to handle, and a 403 is shown as above.

The shell reads meta through U0's `useMetaLive` (`shell/useShellData.ts`): the same `["meta"]` key and `api.meta()` fetcher as `useMeta`, but with a 60 s `staleTime` and `refetchOnWindowFocus`. `queries.ts` stays untouched, and tests that mock `../api` keep working.

**Search button.** The label is `Search`. The key cap reads `⌘K` on Mac (`/Mac|iP(hone|ad)/.test(navigator.platform)`), else `Ctrl K`, coloured `--text-2`. Below 600 px it is icon-only, with `aria-label="Search (⌘K)"`. The button lives inside Topbar, `.search-btn`.

**ThemeToggle** (`components/ThemeToggle.tsx`) gets the `theme-system`, `sun` and `moon` icons from `icons.tsx` instead of `◐☀☾`. The aria-label states the mode: `` `Theme: ${label}. Switch to ${next}` `` with `label` ∈ `system (dark)`, `system (light)`, `light`, `dark`. The resolved system mode comes from `matchMedia("(prefers-color-scheme: dark)")`. Example: `Theme: system (dark). Switch to light`. The `title` equals the aria-label.

### 1.4 Breadcrumbs, document.title, copy-as-CLI (pure: `shell/crumbs.ts`, `shell/titles.ts`, `shell/cliCommands.ts`)

The workspace lives in ContextRoot, so crumbs start after it. The separator is the `chevron-right` icon at 11 px, `--text-3`, `aria-hidden`. The leaf is `<span aria-current="page">`, never a link (this fixes the self-linking crumb). Crumb labels are lowercase CLI nouns; mono applies to identifiers only.

| routeId | Crumbs after ContextRoot | Copy as CLI (first = default; others in a menu) |
|---|---|---|
| `home` | `workspaces` | none |
| `apps` | `apps` | none |
| `experiments` | `ml_app` › `experiments` | `vmn-exp list ml_app` (+ ` --query '<q>'` when `?q`, ` --archived` when `?archived=1`) |
| `run` | `ml_app` › `experiments` › `@54 lr-sweep-3` | `vmn-exp show ml_app -v V`; menu: `vmn-exp restore ml_app -v V`, `vmn-exp rerun ml_app -v V`, `vmn goto -v V ml_app` |
| `code-diff` | `ml_app` › `experiments` › `diff @1 → latest` | `vmn-exp diff ml_app -v @1 -v latest` |
| `compare-runs` | `ml_app` › `experiments` › `compare 3 runs` | `vmn-exp compare ml_app -v A -v B -v C` |
| `overlay` | `ml_app` › `experiments` › `overlay 4 runs` | none (no CLI equivalent; nothing is invented) |
| `tree` | `ml_app` › `stamp tree` [› `0.4.1`] | `vmn show ml_app`; with `?v`: `vmn goto -v 0.4.1 ml_app` |
| `actions` | `ml_app` › `actions` | none |
| `models` / `model` | `models` [› `resnet`] | `vmn-exp model list` / `vmn-exp model show resnet` |
| `reports` / `report` / `report-edit` | `reports` [› `<title or rid>` [› `edit`]] | none |
| `tokens` | `API tokens` | none |
| `not-found` / `sign-in` | `not found` / `sign in` | none |

- **Run crumb.** `@54` is mono; the name is in `--text-2`, ellipsised. With no name, it shows `@54` alone. With no idx, it shows a middle-truncated verstr (`midTruncate(v, 24)`, keeping the hash tail). The full verstr goes in `title`.
- **Run label source.** `idx` and `name` come from detail `idx`/`name` (new, U1), else `findCachedRow` (`queries.ts:94`), else they are omitted. `useRunLabel` reads the query cache only and **adds no request**.
- **Copied commands use the verstr V**, not `@N`: it survives prune, and `vmn goto` needs it. Code-diff copies its URL refs verbatim.
- **Store workspaces** get ` --store <uri>` appended to every `vmn-exp` command (not to `vmn` commands).
- **Quoting.** `shellQuote()` single-quotes any argument outside `[A-Za-z0-9@._+:/=-]`, escaping `'` as `'\''`.
- **Copy button.** `<button class="crumb-copy" aria-label="Copy as CLI: <command>">` with a copy SVG. Success announces `copied` in a polite live region and swaps the icon for 1.5 s. A chevron `aria-haspopup="menu"` opens the other commands. It reuses `CopyButton` copy logic from `components/ui.tsx` where it fits.
- **Truncation.** The `ol` is `flex-wrap: nowrap`. Each `li` is `min-width:0; max-width:28ch; overflow:hidden; text-overflow:ellipsis` with `title`, and the leaf is `flex:1 1 auto`. Below 900 px only the leaf shows, preceded by a `chevron-left` back link (`aria-label="Back to <parent label>"`) to the parent crumb.
- **Override.** When `ctx.override` is set (`not-found`, `sign-in`), `useShellCrumbs` builds crumbs, CLI and title from that routeId instead of `ctx.routeId`.

**document.title** has the form `<subject> · <scope> — vmn-exp`. `subject` is the leaf label and `scope` the nearest container (app, else workspace). On app-scoped routes it gets the prefix `(N stuck) ` when the app's `counts.stuck > 0`.

| routeId | Title |
|---|---|
| `home` | `workspaces — vmn-exp` |
| `apps` | `ml-repo — vmn-exp` |
| `experiments` | `ml_app experiments · ml-repo — vmn-exp` |
| `run` | `@54 lr-sweep-3 · ml_app — vmn-exp` |
| `code-diff` | `diff @1 → latest · ml_app — vmn-exp` |
| `compare-runs` | `compare 3 runs · ml_app — vmn-exp` |
| `overlay` | `overlay 4 runs · ml_app — vmn-exp` |
| `tree` | `stamp tree · ml_app — vmn-exp`; with `?v`: `stamp tree 0.4.1 · ml_app — vmn-exp` |
| `actions` | `actions · ml_app — vmn-exp` |
| `models` / `model` | `models · ml-repo — vmn-exp` / `resnet · models — vmn-exp` |
| `reports` / `report` / `report-edit` | `reports · ml-repo — vmn-exp` / `<title> · reports — vmn-exp` / `edit <title> — vmn-exp` |
| `tokens` | `API tokens — vmn-exp` |
| `not-found` / `sign-in` | `not found — vmn-exp` / `sign in — vmn-exp` |

The `index.html` default becomes `<title>vmn-exp</title>`. On a **pathname** change, the shell writes the title into the `.sr-only` live region and moves focus to `#main`, but only when the navigation came from the palette or the drawer (`location.state?.focusMain`). Mouse users never see focus jump.

### 1.5 ⌘K: CLI grammar (`components/palette/*`, `components/CommandPalette.tsx`)

**Tokenizing** (`parseCliQuery`, pure):

1. Trim the text. Strip a leading `vmn-exp`, `vmn`, `exp` or `experiment`. Tokenize on whitespace, keeping `'…'` and `"…"` spans together.
2. A **ref** is `@\d+`, `@latest`/`latest`, or a verstr or prefix: at least 4 chars of `[A-Za-z0-9._+-]` containing a digit. `-v <ref>`, `--version <ref>` and positional refs are equivalent, matching the CLI (`refs nargs=*`, `-v append`).
3. A positional token equal to an app name or its tag form sets the app. Otherwise the app is `ctx.app`, else the workspace's only app, else the result is `{kind:"error", message:"name an app: show <app> -v <ref>"}`.
4. A bare `@N` or `latest` with no verb means `show`.

| Input | Intent | Destination |
|---|---|---|
| `@54`, `show [app] [-v] <ref>`, a pasted `vmn-exp show ml_app -v @54` | `show` | `runHref(base, verstr)` after the ref resolves |
| `list [app] [--query] <expr…>`, `q <expr>`, `list --archived` | `list` | leaderboard `?q=<expr>` [`&archived=1`] |
| any input containing `metrics.` / `params.` or an operator ` = != < <= > >= ~ in ` | `list` | same as above |
| `compare [app] <ref> <ref>…` / `compare -v a -v b` (2–50 refs) | `compare` | `…/compare-runs?sel=<v>&sel=<v>` |
| `diff [app] a b` / `diff -v a -v b` / `diff -v a --to b` | `diff` | `…/compare?v=a&to=b` (refs as typed) |
| `overlay [app] <ref>…` | `overlay` | `…/overlay?runs=<v>,<v>` |
| `goto [-v] <version> [app]` | `goto` | `…/actions?goto=<version>`, a **prefill only**; the palette never runs a mutation. Alt row: `Open in stamp tree` → `…/tree?v=<version>` |
| `restore <ref>` / `rerun <ref>` | `copy` | Enter copies `vmn-exp restore ml_app -v V` (and similarly for rerun) |
| `tree [version]` | `tree` | `…/tree[?v=]` |
| `status running\|stuck\|failed\|succeeded\|created` | `status` | leaderboard `?status=<s>` |
| `create` / `new` | `create` | leaderboard `?new=1` |
| `models`, `model <name>[@N]`, `reports`, `tokens`, `actions`, `experiments`, `runs`, `apps`, `docs` | `page` | that page |
| `app <name>`, `ws <name>`, or a bare app or workspace name | `app` / `ws` | `/ws/:ws/app/:tag` / `/ws/:ws` |
| anything else | none | fuzzy match over pages, apps and workspaces, plus the existing server run search (`runSearchQuery`) |

**Ref resolution.** Every `@N` and prefix in a command is resolved in **one** request, debounced 150 ms: `api.experimentsPaged(ws, app, {query, limit: refs.length + 20, archived: true})`. The query is `idx in (3, 7)`, OR-ed with `verstr ~ "<prefix>"` for each prefix. `~` is a substring match, so the client keeps only rows whose verstr **starts with** the prefix: exactly one match resolves, none gives `no run matches <ref>`, and several give `<ref> matches several runs; type more of it`. `archived: true` is there because `vmn-exp show -v @N` resolves archived runs too. `latest` resolves through `apiShell.resolveRef(ws, tag, "latest")`. Until the request lands, the row reads `compare @3 @7 · resolving…`.

Disabled error rows (`aria-disabled`, `--text-3`), with exact copy:

- `ml_app has 53 runs (@1–@53)` (when `@N > total`)
- `no run matches 0.2.0.dev9`
- `goto needs a git workspace` (store workspace)
- `read-only server` (`goto` or `create` while `ShellContext.readOnly`)
- `compare needs at least 2 runs`

**Sections.** Each is `role="group"` with `aria-labelledby="cmdk-sec-<key>"`. Headings are visible, 11 px, `--text-2`. Each section shows at most 5 rows, then `N more`, which expands in place.

| Input state | Section order |
|---|---|
| empty | `Recent` (last 5 destinations from `localStorage["vmn-exp:recent"]`, max 20 stored), `Go to`, `Runs` (newest 5), `Apps`, `Workspaces` |
| typed | `Command` (the parsed intent, always first and active), `Runs` (up to 8, plus `All matches in experiments` with a `chevron-right` icon, going to `?q=`), `Go to`, `Apps`, `Models`, `Reports`, `Workspaces` |

`Go to` lists every destination for the context:

- app pages: Experiments, Stamp tree, Actions
- template rows: `Compare runs…` (fills `compare `), `Overlay curves…` (fills `overlay `), `Code diff…` (fills `diff `)
- workspace pages: Apps, Models, Reports
- server: API tokens (same gate as the sidebar: control plane, and auth off or `meta.role === "admin"`), `Docs: vmn-exp ui` (opens `DOCS_URL` in a new tab)
- `New run` (`vmn-exp create`), hidden while read-only or in a store workspace

With no app in context, the app pages and template rows are left out (the palette lists only reachable destinations), and `show`/`compare`/`diff` commands resolve the app by §1.5 step 3.

Models and Reports are fetched with `apiModels.listModels` and `apiReports.listReports` only once the query has at least 2 characters, cached 60 s.

**Row anatomy**, a grid of `20px | 1fr | auto`:

- an SVG kind icon
- primary text: mono for refs, apps and verstrs; `white-space:nowrap; text-overflow:ellipsis`, with the full value in `title`
- secondary text in `--text-2`: `running · 3m ago`, with status as a word
- right column: the CLI equivalent in mono, `--text-3`

For example: `@54  lr-sweep-3  running · 3m ago   show -v @54`, `ml_app  53 runs · 2 stuck   list ml_app`, `Stamp tree  ml_app   vmn show ml_app`.

The placeholder is `@54, show -v <ref>, compare @3 @7, goto <version>, app or page…`. With no match: `No match for "xyz". Try @12, show -v <verstr>, compare @3 @7, or metrics.loss < 0.3.`

The footer hint (11 px, `--text-2`, `aria-hidden`; the same text sits in `aria-describedby`) reads `↑↓ move · ↵ open · ⌘↵ new tab · ⇧↵ copy CLI · tab complete · esc close`.

**Keyboard.** All keys are handled on the dialog element, not `document`.

| Key | Action |
|---|---|
| ↑ / ↓ | move through all rows (wraps) |
| Home / End | first / last row |
| PageUp / PageDown | previous / next section |
| Enter | go (a template row fills the input instead) |
| ⌘/Ctrl+Enter | open in a new tab (`window.open(href, "_blank", "noopener")`) |
| ⇧Enter | copy the row's CLI equivalent |
| Tab | complete the verb or app token (`sh` → `show `, `ml_` → `ml_app `). With nothing to complete, focus stays in the dialog |
| Esc | clear a non-empty input, else close |
| ⌘/Ctrl+K | toggle (the global handler in App) |

**Accessibility.**

- Container: `<div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">`. The `.shell` sibling gets `inert` while it is open.
- `useFocusTrap` keeps focus inside, and focus returns to the opener (`document.activeElement` at open).
- Input: `role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-autocomplete="list" aria-activedescendant="cmdk-opt-<i>"`.
- List: `role="listbox" id="cmdk-list"`. Options: `role="option" id="cmdk-opt-<i>" aria-selected`.
- A polite live region announces `12 results`, debounced 300 ms.
- Veil: `.cmdk-veil { background: color-mix(in srgb, var(--bg) 62%, transparent) }`, so it follows the theme. Below 600 px the width is `min(560px, 100vw - 16px)` with `padding-top: 8vh`.

### 1.6 Not-found and errors (`components/shell/NotFound.tsx`)

There is one component with typed `kind`s. It renders **inside the shell**, with an `<h1 tabIndex=-1>` focused on mount, one body line, up to 3 actions (the first primary), and an optional CLI line with a CopyButton. It calls `useOverrideRoute("not-found")`, so the crumb leaf and title read `not found`. It renders no eyebrow (Eyebrow rule, §0). It must not call `useShellContext` (it renders inside pages tested under `MemoryRouter`); it reads meta and workspaces through `usePageScope` (U0). In the table below, backticks mean mono.

| kind | h1 | Body | Actions |
|---|---|---|---|
| `route` | `No page at this address` | `` `<pathname>` isn't a vmn-exp ui page. `` | **All workspaces**; `Open <ws>` (when the first segment after `/ws/` names a real workspace); hint `⌘K jumps to any run, app or page.` |
| `workspace` | ``No workspace named `x` `` | `Workspaces on this server: a, b.` (links, up to 5), or `This server has no workspaces yet.`; then ``Did you mean `y`?`` (edit distance ≤ 2 or prefix) | **All workspaces**; `Attach a checkout as x` → `/?add=1&name=x` (only when `!meta.read_only` and either auth is off or `meta.role === "admin"`, the role `POST /workspaces` needs); CLI `vmn-exp ui --repo <path>` |
| `app` | ``No app `ml_ap` in ml-repo`` | ``Did you mean `ml_app`?`` then `Apps here: ml_app, eval.`; with zero apps, git: `ml-repo has no apps yet. An app appears after its first vmn stamp -r patch <app> or vmn-exp run <app> -- <cmd>.`; store: `This store has no runs yet.` | **Open ml_app** (the suggestion) or **Open ml-repo**. **No create button and no create hint.** |
| `run` | ``No run `@540` in ml_app`` | `@N` ref: `ml_app has 53 runs (@1–@53).`; other ref: `It may have been pruned (vmn-exp prune), or recorded offline and not pushed yet (vmn-exp push).` | **Back to experiments**; ``Search runs for `0.2.0.dev3` `` → leaderboard `?q=verstr ~ "0.2.0.dev3"`; CLI `vmn-exp list ml_app --query 'verstr ~ "0.2.0.dev3"'` |
| `model` | ``No model `resnet` in ml-repo`` | `It may have been deleted (vmn-exp model delete).` | **All models**; CLI `vmn-exp model list` |
| `report` | ``No report `r_12` in ml-repo`` | none | **All reports** |
| `control-plane` | `API tokens need a control plane` | `This server has no control plane. Start it with vmn-exp ui --config server.yml.` | **All workspaces** |
| `needs-git` | `Stamp tree needs a git workspace` (or `Actions need a git workspace`) | ``team is a store workspace (`s3://team-exp/ml`). Versions live in git tags: open a git workspace of this app, or run `vmn show ml_app` in a checkout.`` | **Open experiments** |

**RouteError** (`components/shell/RouteError.tsx`) is the `errorElement` of **every child route** of `/` (routes stay flat, §3 U9). A child route's error element renders in the parent's `<Outlet/>`, so the shell survives. The root route has no `errorElement`. It sets `useOverrideRoute("not-found")` only for 404-like router errors (`isRouteErrorResponse(e) && e.status === 404`):

| Error | h1 | Body | Actions |
|---|---|---|---|
| message matches `/dynamically imported module\|Importing a module script failed/` | `The dashboard was updated` | `This tab runs an older build. Reload to load the new one.` | **Reload** |
| any other error | `This page failed to render` | `<pre>{message}</pre>` | **Try again** (`navigate(0)`), **All workspaces** |

The in-page `ErrorBoundary` stays.

**Detection rules:**

The guards are **element wrappers**, not layout routes: `<WorkspaceGuard><AppGuard><Leaderboard/></AppGuard></WorkspaceGuard>`. Routes therefore stay flat, `routes[0].children` keeps its `path`s (AppShell tests read them), and a page keeps its mount across param changes. Guards read params with `useParams()` and data with `useWorkspaces`/`useApps`/`useAppStatus`. None of them calls `useMatches`.

- **Workspace.** `WorkspaceGuard` renders its children while `useWorkspaces()` is loading, errored, or lists the name. It renders `kind="workspace"` once the list has loaded without the name.
- **App.** Two signals are needed, because the 5 s app-list TTL hides a just-created app. `AppGuard` renders its children at once and swaps to `kind="app"` only when `useAppExists(ws, tag) === false`.
  - `useAppExists` is `true` when the loaded apps list has the app, or `AppStatus.total > 0`.
  - It is `false` when the list has loaded without the app **and** the status has loaded with `total === 0`, or the status failed with 400 (an invalid tag).
  - It is `undefined` otherwise (loading, or a network error).
  - While it is `false`, `useApps(ws)` refetches every 6 s (`APPS_TTL_SEC + 1`), so an app stamped seconds ago appears on its own.
- **Run.** `Run.tsx` renders `kind="run"` when the detail errors with `status === 404` and `body.detail` starts with `Experiment `, or with a 400 `Invalid version`. Any other error keeps the existing error card. The `@N` total comes from `useFacets(ws, app)?.total`.
- **Model and report.** `ModelDetail.tsx` and `Report.tsx` show their kind on a 404.
- **Control plane.** `Tokens.tsx` shows `control-plane` on a 503. Its body contains `no control plane`, which keeps `Tokens.test.tsx` green.
- **needs-git.** `GitOnly` wraps `tree` and `actions`. It shows `needs-git` when the workspace's `kind === "store"`.
- **Leaderboard empty state** for an existing app: `No runs yet in ml_app. Capture your working state:` + `vmn-exp create ml_app` + the button `New run`. The button renders only when `useAppExists === true`, and not when read-only or in a store workspace (it reads these through `usePageScope`). The toolbar's create button follows the same rule (U10).

**PageFallback** (`components/shell/PageFallback.tsx`) renders its container `<div class="route-fallback" aria-busy="true">` at once, with a visually hidden `role="status"` reading `Loading <label>…`. That keeps AppShell's `.route-fallback` test green. After 150 ms it adds a page-head line plus `<Skeleton/>` inside, so fast loads don't flash.

### 1.7 Sign-in and 401 (`auth/*`, `http.ts`)

**Plumbing.**

- `http.ts`: `get`, `post`, `patch` and `del` all go through one `send(method, path, body?, signal?)`.
- On a 401, `send` parses `{detail, auth}` and calls `reportUnauthorized({hints: body.auth ?? null, method})` from `auth/authState.ts`. It then throws an `HttpError` with `status: 401`.
- There is no `window.prompt` and **no automatic replay**. The token stays in `sessionStorage["vmn_token"]`.

**AuthGate** (`auth/AuthGate.tsx`) wraps the page outlet:

- `state.required && state.method === "GET"`: it renders `<SignIn/>` in place of the page. The sidebar stays.
- `state.required` after a mutation: it renders `<SessionBanner/>` **above** the children. The page stays mounted, so form state is kept. It is not a modal: re-signing in needs no protected focus (craft floor, "a modal for a task that needs neither").

**SignIn** (`auth/SignIn.tsx`) calls `useOverrideRoute("sign-in")`, so the title reads `sign in — vmn-exp`. It renders no eyebrow.

- h1: `Sign in to vmn-exp ui`
- body: `This server at <location.host> requires sign-in.`
- With `hints.oidc`: primary button **Continue with SSO**. It sets `sessionStorage["vmn-exp:return-to"] = pathname + search`, then `location.assign(hints.login_url)`. The callback lands on `/`, and the home redirect (§1.8) consumes the key once, only if it starts with `/` and not `//`.
- With both methods: separator text `or paste a token`.
- With `hints.token`: a field labelled **Token** (`<input type="password" autocomplete="off">`) with help `The --token / VMN_UI_TOKEN value, or a vmnx_… API token.`, and a submit **Sign in**.
- Submit stores the token and calls `api.meta()`. On a 401: `That token was not accepted.` (the token is removed). On a network error: `Can't reach the server.` On success: `clearUnauthorized()` and `queryClient.invalidateQueries()`. The route stays.
- `hints === null` (an older server): it shows the token field only.

**SessionBanner** (`auth/SessionBanner.tsx`): `<section role="region" aria-labelledby>`, placed at the top of `<main>`. Its `h2` is focused when it appears.

- h2: `Session ended`
- body: `Sign in again to continue. Nothing on this page was lost. The action you tried was not sent; retry it after signing in.`
- It embeds the same SignIn form, in compact form.

**Sign out** (`signOut()`): clear `vmn_token`. If `meta.auth.oidc`, also `fetch("/auth/logout", {method: "POST", credentials: "same-origin"})`. This is a raw fetch, because `/auth` is outside `BASE`; errors are ignored. Then clear the query cache and set `required: true` with `method: "GET"`.

**403** is not a sign-in case. Callers keep showing the server text (`Requires role 'editor'`) inline. Nothing is added beyond what pages do now.

### 1.8 Home and landing (`pages/WorkspacesHome.tsx`, `pages/AppsPage.tsx`, `components/AddWorkspace.tsx`)

**Redirects** (`HomeRedirect` logic inside WorkspacesHome) run only on the first entry: `location.key === "default"` and no `location.state?.home`. The order is:

1. A valid `vmn-exp:return-to` → navigate there (`replace`) and delete the key.
2. Exactly 1 workspace with exactly 1 app → `<Navigate replace to="/ws/w/app/<tag>">`.
3. Exactly 1 workspace with several apps → `/ws/w`.

**WorkspacesHome.**

- h1 `Workspaces`.
- Sub copy: `A workspace is a git checkout (its own working tree, .vmn/ and lock) or a store URI read through this server.` This fixes "isolated checkout".
- Tiles: `<article class="ws-tile"><h2><Link class="ws-tile-link">name</Link></h2><span class="kind-badge">git|store</span><CopyPath/></article>`. The link stretches over the tile via `::after`, and CopyPath sits above it (`position:relative; z-index:1`). There is no nested interactive element and no `div onClick`. **Workspace tiles have no dot.**
- Below the tiles: `<details class="add-ws">` with the summary **Attach or clone a workspace**, wrapping `AddWorkspace` (its eyebrow removed). It is closed by default and opens when `?add=1` (prefilled from `?name=`) or when there are zero workspaces. It is hidden when `meta.read_only`, or when auth is on and `meta.role !== "admin"`.
- Empty state: `No workspaces yet. Start vmn-exp ui inside a vmn checkout, or attach one below.`

**AppsPage.**

- h1 `<ws>`. Sub: `3 apps · git · /srv/checkouts/ml-repo`, or `· store · s3://…`.
- Tiles are `<article class="app-tile">` with the stretched link on the name, `<StatusRollup status=…/>`, and the meta `53 runs · 12 versions`. Store workspaces show `53 runs` only.
- Tile status loads lazily through `LazyMount`, so only visible tiles request.
- Empty states:
  - git: `No vmn apps in ml-repo yet. Run vmn stamp -r patch <app> or vmn-exp run <app> -- <cmd> in the checkout.`
  - store: `No runs in this store yet.`
- **The cache card moves off the solo path.** `CacheResync` renders below the grid inside `<details class="cache-details"><summary>Server cache</summary>`, only when `meta.mode === "configured"`. Its eyebrow is removed; the body line is `drift 0  [Resync] [Rebuild]`. Admin gating stays as today (it hides when the status is refused). `CacheResync.tsx` keeps its props and its `Rebuild` button name, so `CacheResync.test.tsx` stays green.

`pages/Dashboard.tsx` keeps only `export { WorkspacesHome } from "./WorkspacesHome"; export { AppsPage } from "./AppsPage";`.

### 1.9 Status rollup (`components/shell/StatusRollup.tsx`)

**Source.** `AppStatus` (U1 endpoint), via `useAppStatus(ws, tag)`. It polls every 15 s while `running + stuck > 0` and every 60 s otherwise, only while the tab is visible (`usePolling`).

**Dot rule** (first match wins):

1. `counts.stuck > 0` → `--hotfix`, the word `stuck`
2. `failed_recent > 0` → `--bad`, `failed` (an old failure alone gives no dot: the rollup is about what needs attention now)
3. `counts.running > 0` → `--accent`, `running`; it pulses only under `prefers-reduced-motion: no-preference`
4. otherwise **no dot**

This is the server's `rollup` field. The always-green `.status-dot` beside apps and workspaces is removed.

**Text** shows only nonzero parts, in this order: `2 stuck · 1 failed (24h) · 3 running`. Each part is a `Link` to the leaderboard, so every number traces to its query. `stuck` and `running` go to `?status=<s>`, whose `total` equals the count (both come from `ordered()` over non-archived rows). `failed (24h)` goes to `?status=failed&sort=finished_at&order=desc`, so the N recent failures are the top N rows; its `title` is `failed in the last 24 h, newest first`. The dot is `aria-hidden`, and the text carries the meaning, so status is never colour-only. `compact` shows the dot plus the first part only, with the full text in `aria-label`.

### 1.10 Responsive (`hooks/useDrawer.ts`, CSS in `styles.css`)

| Width | Behaviour |
|---|---|
| ≥ 1280 px | Full layout. |
| 900–1279 px | The store segment of ContextRoot moves to `title`. |
| < 900 px | Drawer layout (below). |
| < 600 px | The search button is icon-only, the theme toggle moves to the drawer footer, `.content-inner` padding is 12 px, and the IdentityChip shows its initial (full text in `aria-label`). |

**Below 900 px:**

- The sidebar becomes an off-canvas drawer: `#sidebar` gets `position:fixed; width:280px; transform:translateX(-100%)`.
- While closed, it is `inert` (which also hides it from assistive tech). `useDrawer` applies `inert` only while `matchMedia("(max-width: 899px)")` matches, and re-evaluates on change, so the desktop sidebar is never inert. Widening the window with the drawer open closes it.
- The topbar is a single row: the `menu` icon button (`aria-label="Open navigation"`, `aria-expanded`, `aria-controls="sidebar"`), leaf crumb, search icon, identity.
- Opening the drawer:
  - focuses the first nav link
  - sets `inert` on `.main-col`
  - shows the theme veil (`.drawer-veil`, same `color-mix` as `.cmdk-veil`)
- Esc, a veil click or a navigation closes it, and focus returns to the menu button.
- ContextRoot renders at the top of the drawer.
- Content padding is 16 px.

### 1.11 Accessibility and CSS floor (`styles.css`, owned by U9)

- **Skip link.** `.skip-link` comes first and is visible on focus. `<main id="main" tabIndex={-1}>`. Landmarks: `<aside>` with three `<nav>`s, `<header>` with `<nav aria-label="Breadcrumb">`, and `<main>`.
- **Reduced motion.**

  ```css
  @media (prefers-reduced-motion: reduce){
    *,::before,::after{
      animation-duration:.01ms!important;
      animation-iteration-count:1!important;
      transition-duration:.01ms!important;
      scroll-behavior:auto!important
    }
  }
  ```

  It covers `dot`, `rise`, `shimmer`, `flashbg` and `pulse`.
- **Light-mode status pills.** New pill-only tokens leave chart and release colours untouched. They are used by `.status-pill.*` (styles.css) and by the dot colours in `StatusRollup.css` (U0 reads `var(--st-*, <fallback>)`, so it works before U9 lands). Ratios were computed for this plan:

  | Token | Value | Ratio |
  |---|---|---|
  | `--light-st-good` | `#17704f` | 5.31 on `--light-panel-2`, 6.06 on white |
  | `--light-st-bad` | `#a8353a` | 5.69 / 6.49 |
  | `--light-st-stuck` | `#7f5207` | 5.91, and 4.99 on its 12% tint over panel-2 |
  | running | keeps `#2563d6` | 4.80 on panel-2 (the pill has no tint) |

  Dark mode maps `--st-good/--st-bad/--st-stuck/--st-running` to `--good/--bad/--hotfix/--accent`.
- **Sizes.** Nav labels are 11 px with `letter-spacing:.6px`, `--text-2`. Copy-path text is 12 px. The palette kind label is 11 px.
- **Focus.** Nav items, crumbs, tiles and palette rows use `outline: 2px solid var(--accent); outline-offset: 2px` on `:focus-visible`.
- **Browser surfaces.** `::selection { background: color-mix(in srgb, var(--accent) 30%, transparent) }`, `caret-color: var(--accent)` on inputs, and `font-variant-numeric: tabular-nums` on counts in the rollup and tiles. The existing scrollbar theming stays.
- **Fonts are self-hosted.**
  - Dependencies: `@fontsource/ibm-plex-sans` (latin 400/500/600/700) and `@fontsource/ibm-plex-mono` (latin 400/500/600), imported in `main.tsx` as `@fontsource/ibm-plex-sans/latin-400.css` (and so on), so only the latin woff2 files ship. They land in `ui/static/assets/`, which `pyproject.toml` package-data (`static/assets/*`) already includes in the wheel.
  - The Google `<link>`s in `index.html` are deleted. Vite emits the woff2 files into `ui/static/assets`.
  - `vite.export.config.ts` (report export) must not reference Google; it falls back to the `--sans`/`--mono` stacks.
- **Obsolete shell CSS.** U9 deletes the rules replaced by unit-local CSS: `.sb-label`, `.sb-app`, `.sb-nav`, `.host-chip`, `.search-pill`, `.palette*`, the tile `.status-dot` and `.crumbs`. It deletes each only if `grep` shows no remaining user. `.eyebrow` stays (Eyebrow rule, §0).

## 2. Contracts

### 2.1 Backend (U1). Every field is additive; old clients ignore it, and the UI tolerates its absence.

**Where the code goes.** `server.py` is already 601 lines, so its diff stays at about 15 lines. The meta payload, the auth hints and the per-workspace role are pure helpers in a new `ui/shell_meta.py`: `meta_payload(app_state, principal, read_only)`, `auth_hints(chain)` and `workspace_role(app_state, principal, ws_name)`. `server.py`'s `meta()` returns `meta_payload(...)`, `list_workspaces(request)` adds `role`, the `_authenticate` middleware's 401 uses `auth_hints`, and it calls `routes_shell.register(...)` and the `forget` that `register` returns.

**`GET /api/v1/meta`** (VIEWER, as today):

```json
{
  "version": "0.10.2",
  "vmn_exp_version": "0.1.4",
  "read_only": false,
  "mode": "standalone",
  "control_plane": false,
  "auth": {"enabled": true, "token": true, "oidc": false, "api_tokens": false, "login_url": null},
  "principal": {"id": "static-token", "name": "static token"},
  "role": "admin"
}
```

| Field | Value |
|---|---|
| `vmn_exp_version` | `importlib.metadata.version("vmn-exp")`, or `null` on `PackageNotFoundError` |
| `mode` | `"configured"` iff `getattr(request.app.state, "config", None) is not None or app.state.control_plane is not None`, else `"standalone"`. It is read at request time, because `server_app` sets `config` after `create_app` |
| `auth.enabled` | `app.state.auth_enabled` (`bool(chain)`) |
| `auth.token` | any `StaticTokenAuthenticator` in `chain.authenticators` |
| `auth.oidc` | any authenticator with `router` |
| `auth.login_url` | `"/auth/login"` when `auth.oidc`, else `null` |
| `auth.api_tokens` | `control_plane is not None` |
| `control_plane` | `control_plane is not None` |
| `principal` | `{id, name}` of `request.state.principal`, or `null` |
| `role` | `effective_role(principal, None, role_mappings)`, i.e. the role in `*`, when auth is enabled and there is a principal; else `null`. With `auth.enabled` true, `null` means **no global role**, not "everything allowed": the principal may still hold per-workspace roles (see `/workspaces`). With auth off, `null` means everything is allowed |

**`GET /api/v1/workspaces`**: each item gains `"role": "viewer"|"editor"|"admin"|null`, from `effective_role(principal, ws.name, mappings)` (which includes the `*` role). It is `null` when auth is off, or when the principal has no role there. `capabilities` is unchanged: it is set only for store workspaces, and only once probed, so it may be absent.

**401 body**, from the `_authenticate` middleware only. It already answers every unauthenticated `/api` request before any route runs, so `RoleCheck.enforce`'s 401 cannot fire for `/api` and `auth/authz.py` is not touched:

```json
{"detail": "Unauthorized", "auth": {"token": true, "oidc": true, "login_url": "/auth/login"}}
```

`login_url` is `null` without OIDC. The response gets the header `WWW-Authenticate: Bearer`. Only the methods are exposed, never secrets. The guard order is unchanged.

**New `GET /api/v1/workspaces/{ws}/git`** (VIEWER; `_git_workspace`, so a store workspace gets 400 and an unknown one 404) lives in a new `ui/git_context.py` plus `ui/routes_shell.py`:

```json
{"branch": "main", "detached": false, "head": "<40-hex>", "head_short": "e71c74d", "dirty": true, "store": ".vmn/store"}
```

- It runs **one** process, `git --no-optional-locks status --porcelain=v2 --branch --untracked-files=no` with `cwd=ws.path`, `timeout=2`, in the threadpool (a sync route). `--no-optional-locks` keeps it from taking `index.lock`, so it never races a `vmn stamp` or an Actions job:
  - `# branch.oid <sha>` → `head`; `(initial)` → `null`
  - `# branch.head <name>` → `branch`; `(detached)` → `branch: null, detached: true`
  - any line not starting with `#` → `dirty: true`
- `head_short = head[:7]`.
- `store` is `os.path.relpath(local_store_root(ws.path), ws.path)` (`vmn_exp.storage.areas`, so always `.vmn/store`). It is where the UI reads this workspace's runs. A conf `experiment.storage.uri` is not what the UI reads, so it is not shown.
- On failure (non-zero exit, timeout, no git) it still answers 200: `{"branch": null, "detached": false, "head": null, "head_short": null, "dirty": null, "store": ".vmn/store", "error": "<first stderr line or 'timeout'>"}`.
- It is memoized in a `TTLCache(5)` (`ui/memo.py`) keyed by workspace name. `routes_shell.register` returns `forget(ws_name)`, which `remove_workspace` calls next to `app_lists.pop` (one added line).
- It imports nothing from `version_stamp`.

**New `GET /api/v1/workspaces/{ws}/apps/{app_tag}/experiments-status`** (VIEWER) lives in `ui/routes_shell.py` plus pure `ui/status_summary.py`:

```json
{"total": 53,
 "counts": {"created": 0, "running": 2, "stuck": 1, "succeeded": 41, "failed": 9},
 "failed_recent": 1, "recent_sec": 86400, "rollup": "stuck"}
```

- It counts over `leaderboards.ordered(snapshot, schema)`, i.e. non-archived rows with derived status, using `_leaderboard_inputs`. All five keys are always present.
- `failed_recent` counts `failed` rows whose `finished_at` (an ISO string, parsed with `vmn_exp.core.status.parse_iso`) is at least `now - recent_sec`, where `now` is `vmn_exp.core.status._now()` (tests patch it).
- `rollup` is `stuck` if `stuck > 0`, else `failed` if `failed_recent > 0`, else `running` if `running > 0`, else `null`.
- The body is memoized per `leaderboards.etag(snapshot, schema, kind="status", hour=int(now // 3600))` (an `LRU(64)`, `ui/memo.py`) and sent with that ETag via `json_response(payload, etag=, request=)`, so a 304 is free. The `hour` term is needed because the etag's live bucket is `None` while nothing runs, yet `failed_recent` changes as failures age out of the window; the window is therefore accurate to one hour.
- An unknown app answers `total: 0` with all zeros (no 404, so the client's two-signal check holds). An invalid tag answers 400, from `_app_name`, as every app route does.
- Invariant (tested): for `s` in `running`, `stuck`, `failed`, `counts[s]` equals `leaderboards.page(snapshot, schema, status=s, limit=1)["total"]`.

**Run detail** `GET …/experiments/{verstr}` gains `"idx": int|null` and `"name": str|null`. In `experiment_detail()`, when `read_child_row` is given, `row = read_child_row(verstr) or {}` (the resolved verstr; the index rows carry `idx` and `name`, `core/fold.py`). The values are `row.get("idx")` and `row.get("name") or metadata.get("name")`; without `read_child_row`, `idx` is `null`.

No change to `oidc_routes.py`: the return path after login is client-side (§1.7).

### 2.2 Frontend shared types. U0 creates `shell/contracts.ts` (types only) and extends `types.ts`.

```ts
// types.ts (U0 edits; additive)
export type Role = "viewer" | "editor" | "admin";
export interface Workspace {
  name: string; kind: string; path?: string; store?: string;
  capabilities?: string[]; role?: Role | null;
}
export interface Meta {
  version: string; read_only?: boolean;
  vmn_exp_version?: string | null;
  mode?: "standalone" | "configured";
  control_plane?: boolean;
  auth?: { enabled: boolean; token: boolean; oidc: boolean; api_tokens: boolean; login_url: string | null };
  principal?: { id: string; name: string } | null;
  role?: Role | null;
}
// ExperimentDetail gains:  idx?: number | null;  name?: string | null;

// shell/contracts.ts
import type { Meta, Role, Workspace } from "../types";   // noUnusedLocals is on: import only what is used

export type RouteId =
  | "home" | "tokens" | "apps" | "experiments" | "run" | "code-diff" | "compare-runs"
  | "overlay" | "tree" | "actions" | "models" | "model" | "reports" | "report"
  | "report-edit" | "not-found" | "sign-in";
/** Every route's `handle` (routes.tsx, U9). */
export interface RouteHandle { id: RouteId; wide?: boolean }

export interface GitContext {
  branch: string | null; detached: boolean; head: string | null;
  head_short: string | null; dirty: boolean | null; store: string; error?: string;
}
export interface AppStatus {
  total: number;
  counts: Record<"created" | "running" | "stuck" | "succeeded" | "failed", number>;
  failed_recent: number; recent_sec: number;
  rollup: "stuck" | "failed" | "running" | null;
}
export interface AuthHints { token: boolean; oidc: boolean; login_url: string | null }

/** What pages may read (usePageScope, U0): meta + workspaces only, no router
 *  matches, so it works under a plain MemoryRouter. */
export interface PageScope {
  ws?: string; workspace?: Workspace; workspaces: Workspace[];
  isGit: boolean;                 // workspace?.kind !== "store" (true while unknown)
  meta?: Meta;
  metaStatus: "loading" | "ok" | "unauthorized" | "forbidden" | "unreachable";
  metaError: boolean;             // metaStatus === "unreachable" (no HTTP status)
  authEnabled: boolean;           // meta.auth?.enabled ?? false
  role: Role | null;              // workspace.role ?? meta.role ?? null
  readOnly: boolean;
  readOnlyReason: string | null;  // exact §1.3 title strings, rules below
  canAdmin: boolean;              // !authEnabled || meta.role === "admin" (global: /tokens, POST /workspaces)
}

/** What every shell component reads (useShellContext, U0). */
export interface ShellContext extends PageScope {
  routeId: RouteId;
  params: Record<string, string | undefined>;   // deepest match params
  search: URLSearchParams;
  pathname: string;
  // ws: the URL's, else lastWorkspace() on global routes; workspace: undefined while loading or unknown
  wsFromUrl: boolean;
  appTag?: string; app?: string;  // tag form / name form
  appBase?: string;               // `/ws/${ws}/app/${appTag}`
  override: "not-found" | "sign-in" | null;   // from shellOverride (§1.1)
}

export interface RunLabel { verstr: string; idx: number | null; name: string | null }
export interface Crumb { label: string; to?: string; mono?: boolean; title?: string; run?: RunLabel }
export interface CliCommand { label: string; command: string }
export interface CrumbInput {
  routeId: RouteId; ws?: string; app?: string; appTag?: string;
  params: Record<string, string | undefined>; search: URLSearchParams;
  run?: RunLabel; reportTitle?: string; storeUri?: string; // set => store workspace
}

export type NotFoundProps =
  | { kind: "route"; pathname: string }
  | { kind: "workspace"; ws: string }
  | { kind: "app"; ws: string; appTag: string }
  | { kind: "run"; ws: string; appTag: string; ref: string }
  | { kind: "model"; ws: string; name: string }
  | { kind: "report"; ws: string; rid: string }
  | { kind: "control-plane" }
  | { kind: "needs-git"; ws: string; appTag: string; page: "tree" | "actions" };

export const RETURN_TO_KEY = "vmn-exp:return-to";
export const LAST_WS_KEY = "vmn-exp:last-ws";
export const RECENT_KEY = "vmn-exp:recent";
export const DOCS_URL = "https://github.com/progovoy/vmn/blob/master/docs/vmn-exp/ui.md";
```

`readOnly` is true when any of these holds; `readOnlyReason` is the first matching string:

1. `meta.read_only` → `Started with --read-only: actions and edits are off`
2. `authEnabled && role === "viewer"` → `` `Your role in ${ws} is viewer` ``
3. `authEnabled && ws && workspace && role === null` → `` `You have no role in ${ws}` ``
4. a store workspace whose `capabilities` is **defined** and lacks `"edit"` → `This store gives no edit access`. An absent `capabilities` (not probed yet) is unknown and does not set `readOnly`; the server still refuses a write it cannot do.

While meta is loading, `readOnly` is `false` and `role` is `null`. Edit affordances may therefore show for an instant on a read-only server, and its 403 text is the backstop.

### 2.3 Frontend shared modules (U0 owns them; everyone imports them)

| Module | Exports |
|---|---|
| `apiShell.ts` | `apiShell.gitContext(ws): Promise<GitContext>`, `apiShell.appStatus(ws, tag): Promise<AppStatus>`, `apiShell.resolveRef(ws, tag, ref): Promise<{verstr, idx, name} \| null>` (detail with series off: `?series=false&max_points=2`; `null` on 404). It uses `get` from `http.ts` (an import only, no edit) |
| `shell/useShellData.ts` | `useMetaLive()` (queryKey `["meta"]`, `queryFn: api.meta`, staleTime 60 s, `refetchOnWindowFocus: true`); `useGitContext(ws?, enabled)` (queryKey `["git", ws]`, `apiShell.gitContext`, staleTime 5 s, refetch on focus, polls 30 s while visible; callers pass `enabled = isGit`); `useAppStatus(ws?, tag?)` (queryKey `["app-status", ws, tag]`, `apiShell.appStatus`, poll rule §1.9). Every hook returns react-query's result, and none throws to an error boundary |
| `shell/usePageScope.ts` | `usePageScope(ws?: string): PageScope`, built from `useMetaLive` + `useWorkspaces` only. It is the one hook **pages** use (Leaderboard, NotFound, guards, WorkspacesHome, AppsPage, Actions); it is safe under `MemoryRouter` |
| `shell/shellOverride.tsx` | `ShellOverrideProvider({children})`, `useOverrideRoute(id: "not-found" \| "sign-in"): void` (set on mount, cleared on unmount; a no-op without a provider), `useShellOverride(): "not-found" \| "sign-in" \| null` |
| `components/shell/icons.tsx` | `Icon({name, size?})` with `name` ∈ `experiments tree actions apps models reports key menu search copy check chevron-down chevron-right chevron-left external close theme-system sun moon run app workspace page command`, following the Icon rule (§0). Shell units import icons only from here |
| `shell/lastWorkspace.ts` | `lastWorkspace(): string \| null`, `rememberWorkspace(ws: string): void` (sessionStorage `LAST_WS_KEY`) |
| `shell/useShellContext.ts` | `useShellContext(): ShellContext`, for shell components only (they render under a data router). It reads `useMatches()` (deepest `handle as RouteHandle`, `id` defaulting to `"not-found"` when missing), `useLocation`, `usePageScope(ws)` and `useShellOverride()`. It calls `rememberWorkspace` when `wsFromUrl` and the workspace exists. An unknown `:ws` keeps `ws` set (for NotFound) and leaves `workspace` undefined |
| `hooks/useFocusTrap.ts` | `useFocusTrap(ref: RefObject<HTMLElement>, active: boolean, opts?: {initialFocus?: RefObject<HTMLElement>}): void`. Tab and Shift+Tab cycle inside; focus is restored to the previously focused element when it deactivates |
| `components/shell/StatusRollup.tsx` + `.css` | `<StatusRollup status?: AppStatus \| null; href: (s: string) => string; compact?: boolean/>`. It renders nothing for `null`, `undefined` or no nonzero part |
| `util/midTruncate.ts` | `midTruncate(text: string, max: number): string` (keeps the head and the last 8 chars, joined with `…`) |

### 2.4 Unit-to-unit interfaces (consumed only by U9's App.tsx and routes.tsx)

| Owner | Export | Signature |
|---|---|---|
| U2 | `shell/crumbs.ts` | `crumbsFor(input: CrumbInput): Crumb[]` (the leaf is last; ContextRoot not included) |
| U2 | `shell/titles.ts` | `titleFor(input: CrumbInput, opts?: {stuck?: number}): string` |
| U2 | `shell/cliCommands.ts` | `cliFor(input: CrumbInput): CliCommand[]`, `shellQuote(arg: string): string` |
| U2 | `shell/useRunLabel.ts` | `useRunLabel(ws?, appTag?, verstr?): RunLabel \| undefined` (cache-only) |
| U2 | `hooks/useDocumentTitle.ts` | `useDocumentTitle(title: string): void` (sets `document.title`) |
| U2 | `components/shell/Crumbs.tsx` | `<Crumbs root?: ReactNode; crumbs: Crumb[]; cli: CliCommand[]/>`. It renders `<nav aria-label="Breadcrumb"><ol>` with the root as the first `li`, then the copy control |
| U2 | `shell/useShellCrumbs.ts` | `useShellCrumbs(ctx: ShellContext): {crumbs: Crumb[]; cli: CliCommand[]; title: string}` (composes the above, with `useRunLabel`, `useAppStatus` stuck count, report title from the query cache `["report", ws, rid]` if present) |
| U3 | `components/shell/NotFound.tsx` | `default NotFound(props: NotFoundProps)`; `RouteNotFound()` (the `*` element: `kind="route"` with `useLocation().pathname`) |
| U3 | `components/shell/RouteError.tsx` | `default RouteError()` (uses `useRouteError`; set as every child route's `errorElement`) |
| U3 | `components/shell/PageFallback.tsx` | `default PageFallback({label}: {label: string})` |
| U3 | `components/shell/guards.tsx` | `WorkspaceGuard({children})`, `AppGuard({children})`, `GitOnly({page, children}: {page: "tree" \| "actions"; children: ReactNode})`. They are element wrappers (§1.6); each renders `children` or `<NotFound/>` |
| U3 | `shell/useAppExists.ts` | `useAppExists(ws, tag): boolean \| undefined` (`undefined` = unknown yet) |
| U4 | `components/shell/Sidebar.tsx` | `default Sidebar({ctx, onNavigate, footExtra}: {ctx: ShellContext; onNavigate?: () => void; footExtra?: ReactNode})`. It renders the **contents** of `<aside>`: wordmark, scope, navs, foot. Nav links pass `state: {focusMain: true}` only when `onNavigate` is set (the drawer) |
| U5 | `components/shell/Topbar.tsx` | `default Topbar({ctx, crumbs, onSearch, onMenu, menuOpen, onSignOut})`, where `crumbs` is the rendered `<Crumbs/>` node, `onSearch: () => void`, `onMenu?: () => void`, `menuOpen?: boolean`, `onSignOut: () => void` |
| U5 | `components/shell/ContextRoot.tsx` | `default ContextRoot({ctx}: {ctx: ShellContext})` (passed by U9 as `Crumbs.root`) |
| U6 | `components/CommandPalette.tsx` | `default CommandPalette({ctx, onClose}: {ctx: ShellContext; onClose: () => void})` (it fetches its own apps through `useApps`) |
| U6 | `palette/recents.ts` | `pushRecent(entry: {label: string; to: string; kind: string}): void` (U9 calls it on pathname change with the title subject) |
| U7 | `auth/authState.ts` | A module store (`useSyncExternalStore`, no React context, so `http.ts` can call it): `useAuthState(): {required: boolean; hints: AuthHints \| null; method: string \| null}`, `reportUnauthorized({hints, method}: {hints: AuthHints \| null; method: string}): void`, `clearUnauthorized(): void`, `signOut(client: QueryClient, meta?: Meta): Promise<void>`. A GET 401 never downgrades a pending mutation 401 to a GET one, and vice versa: the first report wins until it is cleared |
| U7 | `auth/AuthGate.tsx` | `default AuthGate({children})` |
| U8 | `pages/Dashboard.tsx` | `WorkspacesHome`, `AppsPage` (re-exports; routes.tsx keeps its import) |

`Actions.tsx` (U6) reads `?goto=<version>` once, on mount, into `gotoVerstr` (`useSearchParams`). It never runs it: the user still presses the existing goto button.

## 3. Work units

**Waves:**

- **Wave A** (serial, small): U0 is committed on master first, so every worktree branches with the contracts in place.
- **Wave B** (parallel worktrees): U1 to U8, and U10. None of them edits a hot file. Each puts new CSS in its own `.css` file, imported by its own component.
- **Wave C** (after the wave-B merges): U9 owns `App.tsx`, `routes.tsx`, `main.tsx`, `styles.css`, `index.html`, `package.json` and `package-lock.json`.

`http.ts` is owned by U7. `api.ts`, `queries.ts`, `components/ui.tsx`, `components/StatusPill.tsx` and `util.ts` are owned by nobody and are not edited: new calls live in `apiShell.ts` (U0). Every file below appears in exactly one unit's row. A unit that needs a change in a file it does not own stops and reports it, rather than editing the file.

Every unit follows strict TDD: tests first and red, then green. Files stay at or under about 300 lines. Each unit runs only its targeted tests (`npx vitest run <paths>` from `packages/vmn-exp/webui`, or `./packages/vmn-exp/tests/run_pytest.sh --specific_test <name>`), plus the existing tests named in its row, which must stay green.

**Test mocking rule.** New frontend tests mock `../apiShell` (or the right relative path) and `../api` with `vi.mock`, as the existing tests do. Shell-component tests render under `createMemoryRouter` with handles `{id: …}`. Page and NotFound tests render under `MemoryRouter`, since that is what pages must support.

| Unit | Owns (new unless marked *edit*) | Tests written first (red), and existing tests it must keep green |
|---|---|---|
| **U0 Contracts + shared primitives** (wave A) | `shell/contracts.ts`; `types.ts` *edit* (§2.2); `apiShell.ts`; `shell/useShellData.ts`; `shell/usePageScope.ts`; `shell/shellOverride.tsx`; `shell/lastWorkspace.ts`; `shell/useShellContext.ts`; `hooks/useFocusTrap.ts`; `components/shell/icons.tsx`; `components/shell/StatusRollup.tsx`, `StatusRollup.css`; `util/midTruncate.ts` | **New:** `__tests__/apiShell.test.ts` (URLs; `resolveRef` → `null` on 404, rethrows others); `shell/__tests__/usePageScope.test.tsx` (each readOnly rule 1–4 and its exact string, the absent-`capabilities` case, `canAdmin` with a per-ws admin = false, `metaStatus` for 401/403/network, all under `MemoryRouter`); `shell/__tests__/useShellContext.test.tsx` (lastWorkspace on `/tokens`, unknown ws keeps `ws` and has no `workspace`, routeId default `not-found`, `override` follows `useOverrideRoute`); `shell/__tests__/shellOverride.test.tsx` (set/clear on unmount; no-op without a provider); `components/shell/__tests__/icons.test.tsx` (every name renders a distinct path, `aria-hidden`, `currentColor`, stroke 1.6); `hooks/__tests__/useFocusTrap.test.tsx` (Tab/Shift+Tab cycle, restore on deactivate); `components/shell/__tests__/StatusRollup.test.tsx` (dot rule, text order, links incl. the `failed (24h)` sort link, no dot for old failures, nothing for zeros, `aria-label` in compact); `util/__tests__/midTruncate.test.ts`. **Keep green:** the whole existing suite (U0 only adds) |
| **U1 Backend** | `ui/server.py` *edit* (≤ +15 lines: `meta()` → `meta_payload`, `list_workspaces(request)` + `role`, the 401 body + header in `_authenticate`, `routes_shell.register`, `forget` in `remove_workspace`); `ui/shell_meta.py`; `ui/routes_shell.py`; `ui/git_context.py`; `ui/status_summary.py`; `ui/readers/experiment_detail.py` *edit* (idx/name) | **New:** `packages/vmn-exp/tests/test_ui_shell_meta.py` (no auth: `auth.enabled` false, `role`/`principal` null; `--token` with the bearer: `token · admin`; control plane → `configured` + `api_tokens`; `config` set after `create_app` → `configured`; `vmn_exp_version` is a string, or null when patched to raise `PackageNotFoundError`; a principal with only a per-ws role → `role` null with `auth.enabled` true; workspaces `role` null vs set vs `*`); `test_ui_shell_auth_hints.py` (401 body + `WWW-Authenticate` for token only, an OIDC stub, both; no secret in the body); `test_ui_shell_git_context.py` (clean, dirty tracked edit, untracked-only = clean, detached, initial commit-less repo, not-a-repo → 200 + `error`, store ws → 400, unknown → 404, TTL memo, `forget` on remove, `--no-optional-locks` in argv); `test_ui_shell_status.py` (counts, archived excluded, `failed_recent` window with `_now` patched incl. the hour rollover, rollup precedence, a live run turning stuck across buckets, ETag/304, unknown app zeros, invalid tag 400, the `page(status=s)["total"]` invariant); `test_ui_detail_idx_name.py` (`@N`, prefix and `latest` refs all return the resolved row's idx/name). **Keep green:** `test_ui_api.py`, `test_ui_models_api.py`, `test_ui_auth_static.py`, `test_ui_auth_tokens.py`, `test_ui_authz.py`, `test_fix_ui_perf_serving.py`, `test_packaging_split.py` |
| **U2 Wayfinding model + crumbs** | `shell/crumbs.ts`, `shell/titles.ts`, `shell/cliCommands.ts`, `shell/useRunLabel.ts`, `shell/useShellCrumbs.ts`, `hooks/useDocumentTitle.ts`, `components/shell/Crumbs.tsx`, `components/shell/Crumbs.css` | **New:** `shell/__tests__/crumbs.test.ts` (each §1.4 row, run label with and without idx/name, override routeIds); `shell/__tests__/titles.test.ts` (each title row, `(N stuck) ` prefix only on app routes); `shell/__tests__/cliCommands.test.ts` (quoting incl. `'`, `--store` on `vmn-exp` only, `--query`/`--archived`, run menu uses the verstr, overlay/actions have none); `shell/__tests__/useRunLabel.test.tsx` (detail cache > row cache > none; asserts no fetch); `shell/__tests__/useShellCrumbs.test.tsx` (override wins; report title from cache); `components/shell/__tests__/Crumbs.test.tsx` (`aria-current`, leaf not a link, separator is an SVG with no text, copy + polite `copied`, menu, narrow back link label). **Keep green:** none affected |
| **U3 Not-found + guards** | `components/shell/NotFound.tsx`, `NotFound.css`, `shell/notFoundCopy.ts`, `util/closest.ts`, `components/shell/RouteError.tsx`, `components/shell/PageFallback.tsx`, `components/shell/guards.tsx`, `shell/useAppExists.ts`; *edit*: `pages/Run.tsx` (404/400 branch), `pages/Leaderboard.tsx` (empty-state copy + CTA rule, §1.6), `pages/ModelDetail.tsx`, `pages/Report.tsx`, `pages/ReportEdit.tsx` (404), `pages/Tokens.tsx` (503); `pages/__tests__/Leaderboard.test.tsx` *edit* (line 110: `No experiments yet` → `No runs yet in`, the noun decision; red first) | **New:** `shell/__tests__/notFoundCopy.test.ts` (every §1.6 string); `util/__tests__/closest.test.ts` (distance ≤ 2, prefix, none); `components/shell/__tests__/NotFound.test.tsx` (h1 focused, primary first, attach gated by `canAdmin` and read-only, no create text for `app`, `useOverrideRoute` called; under `MemoryRouter`); `RouteError.test.tsx` (stale chunk vs other, renders inside a parent outlet); `guards.test.tsx` (workspace loading vs missing; the app two-signal table incl. 400 and network; GitOnly on store; children kept mounted across param change); `PageFallback.test.tsx` (`.route-fallback` at once, skeleton only after 150 ms, `aria-busy`); `pages/__tests__/RunNotFound.test.tsx` (`@540` with facets total, a pruned verstr, another 404 detail keeps the error card); `pages/__tests__/LeaderboardUnknownApp.test.tsx` (no `New run` while `useAppExists` is not `true`); `pages/__tests__/ModelReportNotFound.test.tsx`. **Keep green:** `Run*.test.tsx`, `Leaderboard*.test.tsx` (except the one edited line), `ModelDetail*.test.tsx`, `Report*.test.tsx`, `Tokens.test.tsx` (its `/no control plane/` matches the new body) |
| **U4 Sidebar** | `components/shell/Sidebar.tsx`, `components/shell/AppSwitcher.tsx`, `components/shell/Sidebar.css`, `shell/navModel.ts` (pure: groups, items and disabled reasons from `ShellContext`) | **New:** `shell/__tests__/navModel.test.ts` (fixed order across every routeId, each disabled title, tokens gating incl. per-ws admin hidden, active ids, no-app and no-ws states); `components/shell/__tests__/Sidebar.test.tsx` (select named `Workspace`, three `nav` landmarks named App/Workspace/Server, one visible `Workspace` heading, wordmark `vmn-exp` + `state.home`, versions as separate spans, docs URL + `(opens on GitHub)`, 7 distinct icons, last workspace on `/tokens`, unknown ws shows `workspace…`, `footExtra` rendered); `components/shell/__tests__/AppSwitcher.test.tsx` (menu roles, Esc returns focus); `components/shell/__tests__/sidebarCss.test.ts` (reads `Sidebar.css`: `.nav-label` font-size ≥ 11px). **Keep green:** none affected until U9 mounts it |
| **U5 Topbar + identity + theme** | `components/shell/Topbar.tsx`, `ContextRoot.tsx`, `IdentityChip.tsx`, `SearchButton.tsx`, `Topbar.css`; `components/ThemeToggle.tsx` *edit*, `components/ThemeToggle.css`; `components/__tests__/ThemeToggle.test.tsx` *edit* (extend; the existing `/theme/i` assertions stay) | **New:** `components/shell/__tests__/ContextRoot.test.tsx` (each §1.3 row incl. no-commit, dirty badge text + title, store truncation + title, no git request for store); `IdentityChip.test.tsx` (every row incl. 401, 403, unreachable, loading; sign-out menu calls `onSignOut`; never has a `.pulse` class); `Topbar.test.tsx` (read-only badge + reason, `⌘K` vs `Ctrl K`, key cap uses `--text-2` class, menu button only when `onMenu` and with `aria-expanded`); `SearchButton.test.tsx`; `ThemeToggle.test.tsx` additions (label states the resolved mode, an SVG and no `◐☀☾` text). **Keep green:** `AppTheme.test.tsx` (theme button stays inside `banner`) |
| **U6 Palette** | `components/CommandPalette.tsx` *rewrite* (≤ 200), `components/palette/parseCliQuery.ts`, `tokenize.ts`, `paletteItems.ts`, `usePaletteRuns.ts` (moved out of CommandPalette), `useRefResolution.ts`, `PaletteRow.tsx`, `recents.ts`, `palette.css`; `pages/Actions.tsx` *edit* (`?goto=` prefill); *edit*: `components/__tests__/CommandPaletteSearch.test.tsx` and `components/__tests__/fix_components.test.tsx` (render plumbing only: `<CommandPalette ws=… apps=…/>` → `<CommandPalette ctx={fakeCtx(…)}/>`; their assertions do not change) | **New:** `components/palette/__tests__/parseCliQuery.test.ts` (one case per §1.5 row, pasted `vmn-exp`/`vmn` lines, quoting, app positional and tag form, each error string); `tokenize.test.ts`; `useRefResolution.test.tsx` (one request for `compare @3 @7 0.2.0`, prefix uniqueness, several matches, `archived: true`); `paletteItems.test.ts` (section order empty/typed, caps + `N more`, read-only/store gating, no app pages without an app, tokens gate, noun `runs`); `recents.test.ts` (max 20, dedupe); `components/__tests__/CommandPaletteA11y.test.tsx` (dialog/combobox/listbox roles, activedescendant, focus trap + restore, Esc semantics, ⇧↵ copy, ⌘↵ `window.open`, PageUp/Down, Tab completion); `pages/__tests__/ActionsGotoPrefill.test.tsx` (prefills, never calls `run`). **Keep green:** `CommandPaletteSearch.test.tsx`, `fix_components.test.tsx` (assertions unchanged), `Actions` behaviour |
| **U7 Sign-in** | `http.ts` *edit* (`send`, no prompt), `auth/authState.ts`, `auth/AuthGate.tsx`, `auth/SignIn.tsx`, `auth/SessionBanner.tsx`, `auth/auth.css` | **New:** `__tests__/http_auth.test.ts` (401 on get/post/patch/del reports + throws `status: 401`, never calls `window.prompt`, never replays, keeps `body`); `auth/__tests__/authState.test.ts` (first report wins, clear, signOut clears token + cache, raw `/auth/logout` fetch only with OIDC); `SignIn.test.tsx` (token ok/rejected/network, OIDC sets return-to + assigns `login_url`, hints null → token only, `useOverrideRoute("sign-in")`); `AuthGate.test.tsx` (GET 401 → page replaced; mutation 401 → banner above children that stay mounted with their input value); `SessionBanner.test.tsx` (heading focused, region named). **Keep green:** `http_error_body.test.ts`, `http_del.test.ts`, and every test that mocks `../http` |
| **U8 Home** | `pages/Dashboard.tsx` *edit* (re-exports only), `pages/WorkspacesHome.tsx`, `pages/AppsPage.tsx`, `pages/homeRedirect.ts` (pure decision), `components/AddWorkspace.tsx` (moved out of Dashboard), `pages/home.css`; `components/CacheResync.tsx` *edit* (eyebrow removed; props and button names unchanged) | **New:** `pages/__tests__/homeRedirect.test.ts` (return-to valid/`//`/absent, 1×1, 1×N, N×any, not on `state.home`, not after the first entry); `WorkspacesHome.test.tsx` (tiles are links with no nested interactive inside the link, CopyPath outside it, no dot, details collapsed / `?add=1` prefill / zero-workspace open / hidden by `canAdmin` + read-only, the fixed sub copy); `AppsPage.test.tsx` (`53 runs · 12 versions`, store omits versions, StatusRollup per tile via LazyMount, cache card only when `configured`, empty copy git/store). **Keep green:** `CacheResync.test.tsx` |
| **U10 Noun pass** | *edit*: `pages/LeaderboardToolbar.tsx` (`+ New experiment` → `New run`, hidden when `usePageScope` says read-only or store), `components/NewExperiment.tsx` (eyebrow → `<h2>New run</h2>`, button `Create run`, body copy says run), `pages/Compare.tsx` (`two runs`); `pages/__tests__/LeaderboardUrl.test.tsx` *edit* (line 111: button name `+ New experiment` → `New run`, the noun decision; red first) | **New:** `pages/__tests__/NounCopy.test.tsx` (toolbar `New run` shown, hidden on read-only and store; the form heading and button; Compare identical-code copy; no `experiment` noun in those strings). **Keep green:** `Leaderboard*.test.tsx`, `CompareCache.test.tsx`, `CompareTableLink.test.tsx` |
| **U9 Shell assembly + global CSS** (wave C) | `App.tsx` *rewrite* (composition ≤ 150 lines: ShellOverrideProvider, skip link, aside with drawer ContextRoot + Sidebar, Topbar, AuthGate, live region, `useDocumentTitle`, `pushRecent`, ⌘K handler, `inert`, `focusMain`, sign-out wiring); `routes.tsx` (**flat** children with handles `{id, wide}`, the guards as element wrappers, `errorElement: <RouteError/>` on every child, `{path: "*", element: <RouteNotFound/>, handle: {id: "not-found"}}`, `PageFallback` with a label per route); `main.tsx` (font imports); `index.html`; `styles.css` (§1.10, §1.11, deletions); `package.json` + `package-lock.json` (`@fontsource/*`); `hooks/useDrawer.ts`; `__tests__/AppShell.test.tsx` *edit* (fixtures `handle: {page}` → `{id}`; its existing assertions stay, incl. `.route-fallback`, `vmn 1.2.3` and the flat `routes[0].children` paths) | **New:** AppShell additions (skip link is the first tab stop, `main#main`, a bogus URL keeps the sidebar and shows NotFound, a throwing child shows RouteError inside the shell, no `local` pulse, title per route, palette toggle sets `inert` on `.shell`, a NotFound sets the title `not found — vmn-exp`); `hooks/__tests__/useDrawer.test.tsx` (open focus, Esc/nav/veil close, focus return, inert only under the media query, widening closes); `__tests__/staticAssets.test.ts` (index.html has no `fonts.googleapis`/`gstatic`, title `vmn-exp`; main.tsx imports `@fontsource/ibm-plex-sans/latin-400.css` and the mono equivalent); `__tests__/stylesContrast.test.ts` (parses `--light-st-*` and `--light-panel-2` from styles.css, asserts ≥ 4.5:1 on panel-2, white and the stuck 12% tint; asserts a `prefers-reduced-motion: reduce` block; `.copy-path` ≥ 12px). **Keep green:** `AppTheme.test.tsx`, the whole suite |

The units are independent because shell consumers take `ShellContext` and pages take `PageScope`, both from U0. Every wave-B shell component is tested with its own `createMemoryRouter` and handles `{id: …}`, so none waits for U9's routes.

## 4. Integration and verification

### 4.1 Integration checklist (after wave C)

1. `npx vitest run` (the whole webui suite), then `npm run build` from `packages/vmn-exp/webui` to rebuild and commit `ui/static/` (and `ui/export_bundle/`).
2. `docs/vmn-exp/ui.md`:
   - API table: `/meta` fields, `/workspaces` `role`, `…/git`, `…/experiments-status`, detail `idx`/`name`
   - a "Signing in" note
   - the shell keyboard model
3. `docs/vmn-exp/server.md` Authentication section: the 401 `auth` body.
4. `docs/plans/README.md` gets row 19. CLAUDE.md `vmn-exp ui` gets a line on the new endpoints.
5. Merge order: wave-B branches merge in any order (their files are disjoint), then U9 branches from the merged master.
6. Remove the worktrees and branches (`git worktree remove --force`, `git branch -D`), then run `/simplify` on the merged change.

### 4.2 Critique items → units

Every priority issue, persona red flag, minor observation and question in the critique has a row here.

| Critique item | Unit |
|---|---|
| Count/noun mismatch: "54 experiments" (Dashboard) | U8 |
| Count/noun mismatch: palette hint | U6 |
| Count/noun mismatch: leaderboard empty state "No experiments yet" | U3 |
| Count/noun mismatch: toolbar `+ New experiment`, New-run form, Compare copy | U10 |
| "isolated checkout" wrong for stores | U8 |
| Ops cache card on the solo path | U8 (only `configured`, below the grid, collapsed) |
| API tokens always shown | U4 (Server group only with a control plane; admin) |
| Palette veil hardcoded in light mode | U6 (`.cmdk-veil`); U9 deletes `.palette-veil` |
| Blank route fallback | U3 `PageFallback`; U9 wires it |
| Docs link target | U4 (`DOCS_URL`) |
| Self-linking crumb | U2 |
| ~24 ungrouped initial palette rows | U6 |
| Always-expanded add form | U8 |
| Hardcoded `local` chip | U5 |
| Always-green dots | U0 `StatusRollup` + U4/U8; U9 deletes `.status-dot` on tiles |
| No read-only cue | U5 |
| Nav items move | U4 |
| Shared icons | U4 |
| Experiments last | U4 |
| Unstyled native selects | U4 (`Sidebar.css` styles `#ws-select`) |
| Bogus URL drops the shell | U3 + U9 |
| `/tokens` loses the workspace | U0 `lastWorkspace` + U4 |
| Typo'd app pushes create | U3 |
| ⌘K pages = 3 / unreachable destinations / no `@N` / no recents | U6 |
| Run crumb "run" / no `document.title` | U2 |
| Raw router 404 / bare red not-found lines | U3 |
| Wrong workspace shown in the select | U4 |
| Wordmark `vmn ui` | U4 |
| No main / skip link | U9 |
| Unnamed select | U4 |
| Div tiles | U8 |
| Palette semantics | U6 |
| `window.prompt` | U7 |
| Reduced motion | U9 |
| Light pills < AA | U9 |
| `.sb-label` 10 px | U4 (11 px in Sidebar.css); U9 deletes the old rule |
| ⌘K hint 4.49:1 | U5 |
| Copy-path 11.5 px | U9 (`styles.css` `.copy-path` 12 px) |
| No responsive shell | U9 drawer + U2/U5 narrow rules |
| Google Fonts on an air-gapped box | U9 |
| Theme state only in `title` | U5 |
| Colour-only dots | U0 `StatusRollup` |
| Verstr rows wrap mid-token | U6 |
| Help: `docs ↗` to the repo root, no contextual shell help | U4 (`DOCS_URL`), U3 (CLI line on each NotFound), U6 (placeholder, no-match hint, footer keys, CLI column) |
| P2: dots from status facets, chip from `/meta` | U1 (`experiments-status`, `/meta` fields) + U0/U4/U5/U8 |
| P2 optional branch/HEAD; question "topbar reads `ml_app · main @ e71c74d · .vmn/store`" | U1 (`/git`) + U5 (ContextRoot) |
| Question: ⌘K speaks CLI grammar | U6 |
| Question: which shell signal at 100k runs | U1 (status counts are memoized per etag, O(rows) once per generation), U0 `StatusRollup`, U2 (`(N stuck)` title prefix) |
| Question: open on "what changed in this code" | out of scope (§5); the home redirect (U8) and ContextRoot (U5) are the first step |
| Alex: tabs all "vmn" | U2 titles + U9 `index.html` |
| Priya: admin-form landing | U8 (redirect, collapsed form) |
| Priya: can't paste `@54` | U6 |
| Priya: green sidebar while a job is stuck | U1 + U0 + U4 |
| Dana: "local" chip on a server, no identity | U1 + U5 |
| Dana: bare pruned-run error | U3 (`run` kind) |
| Dana: phone unusable | U9 (drawer), U2 (leaf crumb), U5 (icon-only search, initial chip), U6 (narrow palette) |
| Sam: unfocusable tiles | U8 |
| Detector: `.palette-veil` light-mode hardcode (`styles.css:514`) | U6 + U9 |

### 4.3 Verification plan

1. **Unit tests per worktree:** targeted vitest files and targeted pytest (`./packages/vmn-exp/tests/run_pytest.sh --specific_test test_ui_shell`).
2. **On master after merge:**
   - the full webui `npx vitest run`
   - `./packages/vmn-exp/tests/run_pytest.sh --specific_test test_ui` (the exp UI tests)
   - `packages/vmn-exp/tests/test_packaging_split.py` (no `version_stamp` import outside `version_stamp.api`)
3. **Build:** `npm run build` (tsc + both Vite builds). `grep -rE 'googleapis|gstatic' packages/vmn-exp/src/vmn_exp/ui/static packages/vmn-exp/src/vmn_exp/ui/export_bundle` returns nothing. `ls packages/vmn-exp/src/vmn_exp/ui/static/assets/*.woff2` lists the Plex files, and `uv build --package vmn-exp` produces a wheel that contains them.
4. **Screenshots** of a real `vmn-exp ui` on a seeded repo (`tests/seed_ui_test_data.py`), at desktop 1440×900 and mobile 390×844, in both dark and light:
   - home (redirect suppressed via the wordmark)
   - the leaderboard, with a stuck run for the rollup
   - a run, with crumb `@N name`
   - ⌘K empty and with `compare @3 @7`
   - a bogus URL
   - an unknown app and `@540`
   - a store workspace (needs-git)
   - `--token` sign-in
   - `--read-only` (badge)
   - the mobile drawer open
5. **Impeccable:** `impeccable detect` on `packages/vmn-exp/webui/src` (target: 0 shell findings), then re-run the critique on `App.tsx`. The target is ≥ 32/40, with no P1.
6. **Manual a11y pass:**
   - Tab order: skip link first, then sidebar, topbar, main.
   - Palette: VoiceOver announces options and the result count.
   - Light-mode pills: the contrast check passes.
   - `prefers-reduced-motion` stops every animation.

## 5. Out of scope (flagged)

- **CLI copy.** `No experiments found` in `cli/experiment.py` breaks the noun rule; fix it separately.
- **A stamp-tree landing page.** PRODUCT.md calls this undecided, and the critique's question about opening on "what changed in this code" stays open. The ContextRoot `branch @ HEAD` is the first step.
- **`HEAD is <app> <version>`** in ContextRoot. It needs tag parsing through `version_stamp.api`; it is a follow-up.
- **A `similar <text>` palette verb.** The leaderboard similar mode has no stable URL param yet.
- **Cross-app free-text palette search.** `/api/v1/search` takes query-language text only.
- **Global shortcuts beyond ⌘K.**
- **In-page eyebrows.** About 30 cards and sections outside the shell still use `.eyebrow`, which the craft floor bans. Replacing them with headings is a separate pass over the page units.
