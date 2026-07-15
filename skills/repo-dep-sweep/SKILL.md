---
name: repo-dep-sweep
description: Audit dependency risk, then submit deduplicated tracker items with persisted authority or prepare them without changing versions.
version: 1.0.0
user-invocable: true
---

# /repo-dep-sweep — dependency / supply-chain sweeper

Standalone entry point to **loop 7** of the repo-maintenance harness: the auto-review sweeper (loop 4)
pointed at the **dependency surface** instead of our code. Like it, this loop is **SUBMIT OR PREPARE
ONLY** — it submits a WI only with persisted `file_tracker_item` authority and otherwise prepares it.
It never bumps a version; every find re-enters `/repo-triage`, and the bump goes through the gates
(the regression gate especially).

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4.7 + Pitfalls),
   `../repo-maintenance/prompts/dep-sweep.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill (its declared ecosystem + audit recipe).
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-dep-sweep` and record that this command
   owns the returned token. On busy or any nonzero result, stop before touching the backlog, `/goal`,
   or the tracker. Heartbeat immediately before every later durable/shared/remote write; a nonzero or
   `not-owner` heartbeat aborts immediately with no further writes. Release the lease on every
   still-owned exit only when this standalone command acquired it (an inherited conductor token remains
   the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write heartbeat
   gate.
3. **Scope:** the current repo + host. Backlog = `<triage-dir>/backlog.md`; `.last-dep-sweep` = the
   last-audited {lockfile-hash + advisory-feed cursor}.
4. **Pin to `{TARGET_REMOTE}/{TARGET_BRANCH}` from the codebase adapter:** refresh that exact target ref FIRST and audit
   the **resolved** lockfile there, not the working tree's — a find in an off-target lockfile can't land.
5. **Two-source churn-gate (FIRST, every fire):** NO-OP unless the dependency set changed **or** the
   advisory feed advanced — a new CVE can land against an unchanged lockfile (`DESIGN.md` §4.7). Then
   **dispatch a READ-ONLY auditor** (`task` explore/general-purpose; strongest
   available model) running the ecosystem's audit/vuln tool.
6. **Reachability is the bar:** a SECURITY find files a work item only if we resolve a vulnerable
   version **and** the vulnerable path is reachable from our code (the dep-sweep analog of a failing
   repro test — unreachable = log `dep-unreachable` on-disk, never the tracker). HYGIENE finds
   (deprecated/abandoned) file at MED+ only. **Dedup HARD** by advisory-id+package; respect the daily
   cap + open-WI backpressure ceiling. Consult the persisted `file_tracker_item` authority for this
   exact operation: with the grant, file each as its OWN ticket tagged `dep-sweep` (patch/minor →
   likely `VERIFIABLE`; MAJOR/migration → flag `NEEDS-DECISION`); mirror to the backlog. Without the
   grant, persist a complete `dep-sweep-escalated` prepared handoff (advisory id, package, evidence,
   severity, tag, escalation target/status/time) to the on-disk backlog under a valid lease and do not
   submit externally.
7. **Authority-aware completion:** filing to the tracker is the only external write and it happens only
   with the persisted `file_tracker_item` grant; in conservative mode a durable prepared/escalated
   handoff satisfies the round instead — never claim a prepared advisory was filed. **Never bump, never
   edit a lockfile.** Loop-until-
   dry; update `.last-dep-sweep` after a real audit. Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as a daily heartbeat (aligned with the sweeper).
