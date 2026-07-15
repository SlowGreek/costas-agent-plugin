---
name: repo-pr-maintenance
description: Steward maintenance pull requests through reviewer responses, work-item fidelity, gate checks, and target-branch freshness.
version: 1.0.0
user-invocable: true
---

# /repo-pr-maintenance — PR stewardship loop

Standalone entry point to **loop 3** of the repo-maintenance harness. Stewards **every** open PR for
our work items — including ones this run didn't create (pre-existing / teammate / carried-over).

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4.3),
   `../repo-maintenance/prompts/wi-fidelity.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill.
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-pr-maintenance` and record that this
   command owns the returned token. On busy or any nonzero result, stop before touching the backlog,
   `/goal`, or the tracker. Heartbeat immediately before every later durable/shared/remote write; a
   nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the lease on
   every still-owned exit only when this standalone command acquired it (an inherited conductor token
   remains the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write
   heartbeat gate.
3. **Scope:** the current repo + host (`ado-repo_pull_request` / read-only `_thread`, or read-only `gh`
   review queries).
   Backlog = `<triage-dir>/backlog.md` -> `todos`.
4. **Do, per open PR:** (a) handle NEW reviewer comments — create a durable review-handoff artifact
   for **EVERY** actionable comment with `thread/comment ref`, `draft text`, `recommended resolution`,
   `escalation target`, `escalation status`, and `escalation time`; prepare EVERY outward-facing
   reply/comment and review-thread resolution (bot, style, preference, or substantive) and escalate it
   for a human to post; never reply, comment, or resolve a thread autonomously. The artifact is a
   handoff record, not a provider-thread tail: never claim the draft appears in the provider thread.
   A test/coverage ask ->
   a scoped engineer (background `task`; strongest available model) adds it to an owned branch + this
   session verifies; a **human correctness/scope challenge -> run the WI-fidelity verifier first, not a
   glib reply**; (b) proactively
   confirm the PR does its work item (diff vs repro steps); (c) ensure it cleared style/security/3-lens
   gates (run them on any carried-over PR that hasn't); (d) **keep the PR mergeable, but only on branches
   this automation owns.** For a PR on our `ai/wi-<id>-*` branch (or a documented `ai/outdated-closure-*`
   batch branch): if the target moved under it, refresh it (rebase/merge the target per repo policy),
   re-run the gates on the updated tree, and resolve conflicts on that branch, escalating only a conflict
   that needs a product call. Before any refresh, verify the durable **bound** `branch-ownership`
   record in the canonical backlog/log. Its immutable PR identity/URL, source repository identity,
   and exact head ref must match the live PR; a `pending` reservation is only for `/repo-implement`'s
   absent-remote initial push and can never authorize a refresh, rebase, or update. The allowed branch pattern alone is insufficient. If the record is absent,
   pending, failed, or mismatched, stay
   read-only. For a deduped **teammate/human/external branch, stay read-only**: monitor
   its freshness/CI/reviews and prepare a concrete patch/rebase/fix recommendation for the branch owner,
   then **escalate** — never push or mutate their branch. Keep such an item `IN-REVIEW`/blocked with the
   handoff recorded rather than pretending it was refreshed. A green PR gone stale against the target is
   not actually landable. Delegate the multi-PR comment poll to a background `task` agent to keep context
   clean.
5. **Authority:** prepare **every** outward-facing reply, comment, and review-thread resolution — bot,
   style, preference, or substantive alike — and escalate it for human posting.
   The loop will never submit outward-facing text autonomously and **never post, send, or resolve** a thread itself.
   Push only when explicit push authority was granted **and** both checks pass: the live branch is the
   PR's `ai/wi-<id>-*` or documented `ai/outdated-closure-*` branch, and its durable **bound**
   `branch-ownership` record matches the live PR's immutable identity, source repository identity,
   and exact head ref. An unrecorded, pending, failed, or mismatched branch — including one with an
   allowed prefix — and every
   teammate/human/external branch stay read-only, recommend-and-escalate; never force/delete, never
   push directly to the target/protected branch. Keep PRs DRAFT. Drain-aware: no-op when every actionable comment has a current
   review-handoff artifact with an escalated status and every open PR is WI-faithful and gate-checked;
   owned branches are current, while external-branch freshness handoffs are recorded. Release the lease
   (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as an hourly heartbeat.
