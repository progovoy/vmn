---
target: whole app shell + navigation
total_score: 22
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/Users/pavelr/projects/vmn/packages/vmn-exp/webui/src/App.tsx"
target_fingerprint: "sha256:f449e387e9569437a224068f9826b0d01dd95a410150c0fc4e391a28a2b47ba8"
target_path: /Users/pavelr/projects/vmn/packages/vmn-exp/webui/src/App.tsx
timestamp: 2026-10-12T07-12-46Z
slug: packages-vmn-exp-webui-src-app-tsx
---
Method: dual-agent (A: design-review subagent · B: detector/browser subagent)

# Critique — vmn-exp dashboard: app shell + navigation
Target: packages/vmn-exp/webui/src/App.tsx (+ routes.tsx, Dashboard.tsx, CommandPalette.tsx, http.ts, shell CSS). Mode: Operate.

## Design Health Score
| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 2 | Hardcoded pulsing "● local" chip (App.tsx:191-194); app/workspace dots always green; no read-only cue |
| 2 | Match System / Real World | 3 | Count/noun drift: "54 experiments" vs "32 of 53 runs" vs "run" |
| 3 | User Control and Freedom | 2 | Bogus URL drops the whole shell; /tokens loses workspace context |
| 4 | Consistency and Standards | 2 | Nav items move between routes; 3 items share one icon (App.tsx:39-44); unstyled native selects |
| 5 | Error Prevention | 2 | Typo'd app URL renders empty app with primary "+ New experiment" |
| 6 | Recognition Rather Than Recall | 2 | ⌘K pages = 3 only; compare/overlay/diff unreachable; run crumb "run"; title always "vmn" |
| 7 | Flexibility and Efficiency | 3 | Server-side ⌘K search; no other shortcuts, @N jump or recents |
| 8 | Aesthetic and Minimalist Design | 3 | Home leads with Add-workspace form; cache ops card above app tiles |
| 9 | Error Recovery | 1 | Raw router 404 with no shell (no errorElement / * route); bare red not-found lines |
| 10 | Help and Documentation | 2 | "docs ↗" → repo root; no contextual shell help |
| **Total** | | **22/40** | **Acceptable** |

## Design Specificity Verdict
Shell is category-interchangeable; product character lives only inside pages (CLI echoes, dry-run previews, stamp tree). Frame never shows git/HEAD/branch/store/verstrs; wordmark says "vmn ui" (App.tsx:92) not vmn-exp.
Detector: shell files 0 findings; whole src 1 (side-tab styles.css:862, plausibly intentional). Browser: shell-wide .sb-label 10px (styles.css:166), ⌘K hint 4.49:1 (styles.css:247), copy-path 11.5px (styles.css:198); light-mode status pills 4.0–4.4:1 (real, missed by design review). False positives: em-dash (200 "—" placeholders), 200× repeated host badge, .card.flush padding, placeholder contrast, 10.5px th headers. Overlay injected in headless Chrome only; no user-visible overlay.

## Priority Issues
- [P1] Not-found/route fallbacks break or mislead (no errorElement/*; bad app pushes create; dead-end red text; wrong workspace shown). Fix: in-shell typed, actionable NotFound; create CTA only when app exists. → /impeccable harden
- [P1] Wayfinding: unlabeled mixed scopes, moving items, Experiments last, shared icons, crumbs "ml_app / ml_app / run", no document.title. Fix: fixed App→Workspace→Server groups, distinct icons, typed crumbs with name + @N, per-route titles, keep workspace on global pages, wordmark vmn-exp. → /impeccable layout
- [P2] Status indicators lie (static local chip, always-green dots, no identity/role/read-only). Fix: chip from /meta, dots from status facets, optional branch/HEAD. → /impeccable clarify
- [P2] Shell a11y: no main/skip link (~14 tabs), unnamed workspace select (App.tsx:96-110), div tiles (Dashboard.tsx:106-110), palette lacks dialog/listbox/focus trap, window.prompt token gate (http.ts:23), no reduced-motion, light pills <AA. → /impeccable audit
- [P2] No responsive shell: fixed 250px sidebar, ~140px content at 390px, crumbs overlap search. Fix: drawer <900px. → /impeccable adapt

## Persona Red Flags
- Alex: ⌘K lacks models/reports/compare/@N; verstr-only rows wrap mid-token; tabs all "vmn"; no recents.
- Sam: unnamed select, unfocusable tiles, palette semantics, no skip link, theme state only in title, colour-only dots, no reduced-motion.
- Priya (solo, from terminal): admin-form landing, can't paste @54, green sidebar while job stuck, Google Fonts on air-gapped box.
- Dana (team lead, shared link): window.prompt token, "local" chip on server, no identity, bare pruned-run error, phone unusable.

## Minor Observations
Count/noun mismatch; "isolated checkout" wrong for stores; ops cache card on solo path; API tokens always shown; palette veil hardcoded in light mode (styles.css:514); blank route fallback; docs link target; self-linking crumb; ~24 ungrouped initial palette rows; always-expanded add form.

## Questions to Consider
- Why open on a workspace admin form instead of "what changed in this code, and which runs came from it"?
- What if the topbar read `ml_app · main @ e71c74d · .vmn/store` instead of "local"?
- Could ⌘K speak CLI grammar (@54, show -v, compare @3 @7, goto)?
- At 100k runs, which shell-level signal (stuck/failed/running per app) should never require opening a leaderboard?
