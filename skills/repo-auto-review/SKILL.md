---
name: repo-auto-review
description: Sweep read-only for reproducible bugs, then submit tracker items with persisted authority or prepare them without fixing code.
version: 1.0.0
user-invocable: true
---

# /repo-auto-review — bug-sweeper loop

Standalone entry point to **loop 4** of the repo-maintenance harness: a read-only discovery sweep
that feeds the backlog. **It never fixes — every find re-enters `/repo-triage`.**

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4 + Pitfalls),
   `../repo-maintenance/prompts/auto-review.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill.
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-auto-review` and record that this
   command owns the returned token. On busy or any nonzero result, stop before touching the backlog,
   `/goal`, or the tracker. Heartbeat immediately before every later durable/shared/remote write; a
   nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the lease on
   every still-owned exit only when this standalone command acquired it (an inherited conductor token
   remains the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write
   heartbeat gate.
3. **Scope:** the current repo + host. Backlog = `<triage-dir>/backlog.md`; `.last-swept-head` = the
   last sweep commit.
4. **Pin to `{TARGET_REMOTE}/{TARGET_BRANCH}` from the codebase adapter:** refresh that exact target ref FIRST and **verify each
   find's file exists on target before filing** (the on-disk checkout can be a stale/dead branch — a
   bug found only in off-target code can't land).
5. **Dispatch a READ-ONLY sweeper** (`task` explore/general-purpose; strongest
   available model) over a not-yet-swept subsystem.
   For each real candidate with a concrete repro + file:line: **dedup HARD** vs the backlog + open
   PRs, then consult the persisted `file_tracker_item` authority for this exact operation. With the
   grant, **FILE a work item** (carry the repro; tag `auto-review`). Without it, persist a complete
   `auto-review-escalated` prepared handoff (title, repro/evidence, severity, tag, escalation
   target/status/time) to the canonical backlog under a valid lease and do not submit externally.
   Loop-until-dry (stop after K
   empty rounds); then a cheap churn-check (HEAD vs `.last-swept-head`) until in-scope code moves.
6. **Authority-aware completion:** filing to the tracker is the only external write and it happens only
   with the persisted `file_tracker_item` grant; in conservative mode a durable prepared/escalated
   handoff satisfies the round instead — never claim a prepared find was filed. **Never fix.** Update
   `.last-swept-head` after a real sweep. Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as a daily heartbeat.
