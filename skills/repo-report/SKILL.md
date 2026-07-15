---
name: repo-report
description: Write a maintenance digest covering backlog dispositions, PR progress, gate catches, friction, and human decisions.
version: 1.0.0
user-invocable: true
---

# /repo-report — report cadence

Standalone entry point to **loop 5** of the repo-maintenance harness: the accountability +
continuous-improvement layer over loops 1-4 and 6.

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§ report),
   `../repo-maintenance/prompts/report.md`, and
   `../repo-maintenance/HARNESS-COPILOT.md`.
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-report` and record that this command
   owns the returned token. On busy or any nonzero result, stop before touching the backlog, `/goal`,
   or writing the digest. Heartbeat immediately before every later durable/shared/remote write; a
   nonzero or `not-owner` heartbeat aborts immediately with no further writes. Release the lease on
   every still-owned exit only when this standalone command acquired it (an inherited conductor token
   remains the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write
   heartbeat gate.
3. **Scope:** read the current repo's `<triage-dir>/backlog.md` + recent `reports/` digests (read-only
   — this loop does NOT touch the repo or its host state).
4. **Write** `<triage-dir>/reports/<today>.md`: items by disposition; PRs opened/advanced/landed;
   sweeper finds (incl. sub-threshold); reviewer comments handled, **each mapped to a concrete
   improvement** to the codebase skill / a gate / a prompt; the gate catch-rates; the friction it hit
   (honestly, skips included); and **what needs the human** (NEEDS-DECISION / NEEDS-QA + escalations).
   The FILE is the source of truth.
5. **Notify (authority-gated, best-effort):** an outbound notification is outward-facing communication
   like any other, so consult the persisted `send_alert` authority before sending anything. **With the
   grant**, use an available notification integration to send a one-line "digest ready" pointer; a
   missing/expired credential or tenant is a clean, distinct skip, never a hang or a headless
   interactive re-auth. **Without the grant** (default conservative mode), do not send: prepare the
   exact notification text and surface it, escalated, alongside the digest path in the run result —
   never claim it was sent. The digest **file** is always the source of truth regardless of delivery.
   Release the lease (§2) on every exit path.

To run this continuously, `/maintain-repo` arms it at a fixed daily cadence (`cron_expression "0 17 * * *"`).
