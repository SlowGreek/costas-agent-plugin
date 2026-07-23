---
name: repo-ci-health
description: Detect same-commit flaky tests, then submit authorized or prepare de-flake WIs and gated quarantine drafts.
version: 1.0.0
user-invocable: true
disable-model-invocation: true
---

# /repo-ci-health — CI / flaky-test health loop

Standalone entry point to **loop 8** of the repo-maintenance harness. Every gate trusts the test
signal; this loop keeps that signal trustworthy — it hunts tests that are **non-deterministic on
identical code**, because a flaky verifier is worse than none (`DESIGN.md` §4.8).

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§4.8),
   `../repo-maintenance/prompts/ci-health.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's `<repo>-codebase`
   skill (its test/build recipe + CI host).
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-ci-health` and record that this command
   owns the returned token. On busy or any nonzero result, stop before touching the backlog, `/goal`,
   or the tracker. Heartbeat immediately before every later durable/shared/remote write; a nonzero or
   `not-owner` heartbeat aborts immediately with no further writes. Release the lease on every
   still-owned exit only when this standalone command acquired it (an inherited conductor token remains
   the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write heartbeat
   gate.
3. **Scope:** the current repo + CI host (`ado-pipelines_*` / `gh run list` + per-run results). Backlog
   = `<triage-dir>/backlog.md`; `.last-ci-scan` = the last-mined run id.
4. **Detect (read-only):** pull the last N runs per test; a **flake candidate** shows BOTH outcomes on
   the SAME sha (or fails→passes on a bare re-run). Rank by flake-rate × how many PRs it's blocked.
   Dispatch the mining to a background `task` agent using the strongest
   available model to keep context clean.
5. **False-quarantine guard (critical):** require ≥M observed both-outcome runs on one sha before
   calling a test flaky; a **consistently-red** test is a real failure → Triage as a normal bug, NEVER
   quarantine; if the non-determinism is in the PRODUCT (a genuine race), route the product bug through
   the same persisted `file_tracker_item` authority or prepare/escalate it, and do **not** quarantine
   (that would hide a live race). Quarantine is for TEST-harness non-determinism only.
6. **Act:** for each confirmed harness flake, consult persisted authority for each exact operation:
   `file_tracker_item`, `initial_push`, `open_draft_pr`, `send_alert`, and later push/update. Submit the
   de-flake WI first (tag `ci-health`, contradictory runs) only with `file_tracker_item`; otherwise
   prepare/escalate it and do not push or open. Quarantine transport explicitly invokes the harness's
   global two-phase canonical `branch-ownership` procedure: require that live submitted WI and BOTH
   persisted `initial_push` and `open_draft_pr` grants in the pending absent-head reservation, then one
   initial push, immediate **DRAFT** PR binding, and freeze/escalation on bind failure. A lone
   `open_draft_pr` grant never supplies push authority. Later mutation requires the bound live
   source/head match and applicable push/update authority. If any prerequisite is absent, persist a
   complete drainable `ci-health-escalated` prepared handoff (WI body, quarantine-draft body, evidence,
   requested operation, escalation target/status/time) and do not submit externally. Backlink only
   under its exact grant.
   Implement writes the deterministic fix and lifts a submitted quarantine in the same PR. Broader CI
   health (build-time regressions, build-result gate integrity §8) is report-only. **Dedup** by test id
   + signature.
7. **Authority-aware completion:** a current fire completes each confirmed flake only with the
   authority-permitted submitted artifact(s), or in conservative mode with its durable prepared/escalated
   handoff; never claim a prepared WI, alert, or draft was submitted. Default conservative mode submits
   nothing externally. NO-OP when no new CI runs. Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it as an hourly heartbeat (after CI activity).
