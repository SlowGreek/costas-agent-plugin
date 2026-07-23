---
name: repo-triage
description: Classify every maintenance backlog item into a proven disposition with its required evidence.
version: 1.0.0
user-invocable: true
disable-model-invocation: true
---

# /repo-triage — backlog triage loop

Standalone entry point to **loop 1** of the repo-maintenance harness: the backlog reviewer for every
new item (filed, swept, or engineer-discovered).

## Run
1. **Load the harness:** resolve this skill's base directory, then read
   `../repo-maintenance/SKILL.md` (§3 taxonomy),
   `../repo-maintenance/DESIGN.md`, `../repo-maintenance/prompts/triage.md`,
   and `../repo-maintenance/HARNESS-COPILOT.md`; load the repo's
   `<repo>-codebase` skill.
2. **Resolve identity and acquire the lease** (before any durable/shared/remote write, including
   `/goal`): resolve the sibling `repo-maintenance` directory and run
   `runtime/repo_identity.py --cwd <repo-root>` (read-only) for its `state_dir`/`backlog_path` — this is
   `<triage-dir>`. If the conductor already supplied a token, verify ownership with
   `runtime/maintenance_lock.py heartbeat` and retain it; otherwise acquire with
   `runtime/maintenance_lock.py acquire <state_dir> --loop repo-triage` and record that this command
   owns the returned token. On busy or any nonzero result, stop before touching the backlog, `/goal`,
   or the tracker. Heartbeat immediately before every later durable/shared/remote write; a nonzero or
   `not-owner` heartbeat aborts immediately with no further writes. Release the lease on every
   still-owned exit only when this standalone command acquired it (an inherited conductor token remains
   the conductor's). See `HARNESS-COPILOT.md`'s invocation contract for the full pre-write heartbeat
   gate.
3. **Scope:** the current repo + its host (`ado-*` MCP tools or `gh`). Backlog = the harness's
   durable file `<triage-dir>/backlog.md`; reload its rows into the `sql` `todos` table.
4. **Do:** classify every UNTRIAGED item into exactly one disposition, **attaching its artifact**.
   Run the staleness gate + the feasibility/data-existence pre-check. For a bulk/initial backlog,
   **fan out a swarm of background `task` agents** (one per slice of items,
   pre-checks in parallel; strongest available model) and
   merge dispositions back to the file. New `VERIFIABLE` items hand off to `/repo-implement`;
   `NEEDS-DECISION`/product escalate. Write every disposition back to the file.
5. **Drain-aware:** no-op if nothing is untriaged. Triage itself never pushes. Release the lease (§2)
   on every exit path.

To run this continuously, `/maintain-repo` arms it as an hourly heartbeat.
