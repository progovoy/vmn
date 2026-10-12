---
target: whole app shell + navigation (after plan 19)
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/Users/pavelr/projects/vmn/packages/vmn-exp/webui/src/App.tsx"
target_fingerprint: "sha256:07dc8f6b198306d80e3284c461a3cf0d92e54994c731d6a760ba00087f58685b"
target_path: /Users/pavelr/projects/vmn/packages/vmn-exp/webui/src/App.tsx
timestamp: 2026-10-12T09-48-04Z
slug: packages-vmn-exp-webui-src-app-tsx
---
Method: dual-agent (A: design-review subagent · B: detector/browser subagent) — post plan-19 re-critique

# Critique — vmn-exp dashboard: app shell + navigation (after plan 19)

## Design Health Score
| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Rollup, stuck count in title, branch@sha context, live region; counts disagree (apps 54 runs vs leaderboard 32 of 53) |
| 2 | Match System / Real World | 3 | CLI nouns; crumb repeats ml_app when ws = app; `.vmn/store` path in primary chrome |
| 3 | User Control and Freedom | 3 | Esc/veil/back/recovery everywhere; first Esc in a filled ⌘K only clears |
| 4 | Consistency and Standards | 2 | CLI hints differ (`list ml_app` vs `vmn-exp list ml_app`); native Models select; /tokens crumb "not found"; unknown app shows switcher active |
| 5 | Error Prevention | 2 | ⌘K Recent records dead destinations; nav lets you go deeper inside a nonexistent app |
| 6 | Recognition Rather Than Recall | 3 | Recent + teaching empty state + CLI per row; copy-as-CLI icon faint; query language help = placeholder |
| 7 | Flexibility and Efficiency | 3 | ⌘K grammar, ⌘↵/⇧↵/Tab, skip link; no single-key nav; 13 sidebar tab stops |
| 8 | Aesthetic and Minimalist Design | 2 | Shell calm; leaderboard header ~22 controls; "best" on every sparkline |
| 9 | Error Recovery | 3 | Not-found pages name thing, cause, escape, CLI fix |
| 10 | Help and Documentation | 1 | Only a Docs link + tooltips; no query-language or goal-arrow help |
| **Total** | | **25/40** | **Acceptable** |

## Design Specificity Verdict
Now product-specific: crumb root reads like a prompt (`ml_app main @ e71c74d · .vmn/store`), ⌘K speaks CLI grammar with CLI per row, not-found pages carry the CLI fix. Generic residue lives in pages (leaderboard toolbar wall, native selects, Reports form).
Detector: shell source 0 findings (23 files + shell CSS); whole src 1 (side-tab styles.css:806, error card accent). Browser: 0 findings on any shell element; 311 page-body findings (dense-table sizing, 200× one inline 10px badge RunLog.tsx:83, em-dash false positive from `step N — ` log rows, placeholder #757575, created pill 4.49:1).

## Priority Issues
- [P1] Leaderboard header overload (~22 equal-weight controls before data). → /impeccable distill, /impeccable layout
- [P1] "best" crowned on every metric sparkline, incl. epoch/lr_sched. Show best only with a goal. → /impeccable clarify
- [P2] Inconsistent CLI hints (⌘K omits `vmn-exp`), crumb repeats ws=app name, store path in chrome. → /impeccable clarify
- [P2] Shell trusts bad state: Recent records failed destinations, unknown-app switcher/nav active, /tokens crumb "not found". → /impeccable harden
- [P2] Mobile chrome: run header wraps, ⌘K hint on touch, palette CLI column truncates, unexplained "L" identity initial. → /impeccable adapt

## Persona Red Flags
- Alex: no single-key nav; Esc-clears-first; 13 tab stops.
- Sam: sidebar h2s precede page h1; faint copy button; status chips vs similar toggle look alike.
- Priya: ⌘K hints omit vmn-exp so pasted commands fail; count mismatch.
- Dana: redirect gives no orientation beat; local paths lead the sidebar on a server; identity chip unclear; no share affordance.

## Minor Observations
Models native select + "—" descriptions; Reports redundant subtitle; sparkline y-labels clipped (Y_AXIS_SIZE 56); apps rollup single amber dot; visible rollup "1 stuck" vs aria-label all counts; Recent icon inconsistency; duration/runtime both 0s; dark sidebar vs content barely separate; store /tree issues one 400 before needs-git; .select-wrap ▾ glyph in Actions/RunPicker.

## Questions to Consider
- Why lead with 11 sparklines of run-index noise instead of runs and their commits?
- Should `/` show one orientation beat (ws, app, branch@sha) before redirecting?
- Could the leaderboard filter row be one CLI-grammar input with chips as completions?
- Is the store path navigation, or provenance for a popover?
