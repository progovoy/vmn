# Development rules for AI agents (optional)

These are optional, opinionated development rules for AI coding agents. They
are not part of `vmn skill` and nothing in vmn generates or installs them —
copy the sections that fit your team into your `CLAUDE.md`, `AGENTS.md`, or
`.cursorrules`.

## Development gold rules

> Follow these rules. If your CLAUDE.md or project instructions explicitly
> contradict a rule below, the project instruction wins.

### Testability by design
- Every non-deterministic or side-effectful dependency (network, disk, clock, randomness, environment) must be an injected interface, created at the application boundary and passed inward.
- New code must be testable with fast, in-process tests — no containers, no real I/O, no sleeps. If you can't test it without a running service, the design is wrong.
- When touching existing code that violates this, extract the I/O behind an interface in a separate preparatory commit before adding new behavior.

### TDD (strict)
1. **RED** — Write the failing test first. It must fail for the right reason (not a syntax error or import failure).
2. **GREEN** — Write the minimum implementation to make it pass. Do not modify the test.
3. **REFACTOR** — Clean up implementation only, keeping tests green.

Rules:
- No implementation code exists without a test that demanded it.
- Never weaken, delete, or rewrite a test to make it pass — if the test seems wrong, stop and ask.
- Config-only changes, documentation, and pure refactors (where existing tests still cover behavior) are exempt.
- **Parallel worktrees do not bypass TDD.** Each worktree must follow its own red-green-refactor cycle internally. Write tests first in the worktree, then implement.

### Boy Scout rule
- When you're already modifying a function or file, improve clarity of what you touch — rename an unclear variable, simplify a conditional, extract a helper.
- Don't refactor code you're not otherwise changing. The improvement must be in the natural path of the current task, not a detour.
- If you spot a larger cleanup opportunity outside your current scope, spawn a subagent in a separate worktree to handle it — don't block or pollute the current task's diff.

### Parallel worktree workflow
- Split big tasks into separate git worktrees and run in parallel, but **TDD takes precedence**. Each worktree agent must follow TDD internally: write tests first (red), then implement (green). If multiple worktrees touch independent features, each worktree owns its own red-green-refactor cycle.
- Never push worktree branches to remote — they are local-only.
- Run the full test suite in the worktree before merging back.
- Run `/simplify` on the finished change before merging (Claude Code) — it catches reuse opportunities and unnecessary complexity while the context is fresh.
- A task is not done until it is merged and pushed. Before merging, ask the developer which branch to merge into.
- Verify no work is lost (`git diff` and `git log` against merge target) before removing a worktree.
- Remove worktrees immediately after merging (`git worktree remove --force`, then `git branch -D`). Run `git worktree list` at session start and clean up stale ones.

### Communication
- If the task is ambiguous or has multiple valid interpretations, ask one clarifying question before starting — don't guess at requirements.
- If a request seems over-engineered for the problem, say so and propose the simpler alternative.
- If you're blocked or uncertain about a design choice with significant downstream impact, surface it rather than picking silently.
- Don't ask for confirmation on clear, low-risk, reversible actions — just do them.

### Minimal diffs
- Every commit does one thing. Don't mix refactoring with behavior changes.
- Don't add code that isn't exercised by the current task — no speculative helpers, unused parameters, or dead feature flags.
- Prefer deleting dead code over commenting it out. Version control is the archive.
- When a change touches many files, verify the diff contains no accidental formatting or whitespace noise.

### Error handling
- Handle errors at the level that can do something useful about them. Don't catch-and-rethrow, don't log-and-ignore.
- Fail fast and loud on programmer errors (wrong types, broken invariants). Only retry on transient external failures.
- Error messages must say what went wrong, what was expected, and (when possible) what the user should do. No naked stack traces to end users.
