---
name: repo-learn
description: Onboard a repository into a reusable codebase skill and prove its test recipe before maintenance loops run.
version: 1.0.0
user-invocable: true
---

# /repo-learn — onboard a repo

Standalone entry point to **Phase 0** of the repo-maintenance harness: author the repo's codebase
skill and crack its build. Run this once per repo before any maintenance loop.

## Run
1. **Load the recipe:** resolve this skill's base directory, then read
   `../repo-maintenance/bundled/learn.md` and
   `../repo-maintenance/HARNESS-COPILOT.md`.
2. **Resolve identity:** resolve the sibling `repo-maintenance` directory and run
   `python3 <repo-maintenance-dir>/runtime/repo_identity.py --cwd <repo-root>`.
   Use its exact `repo_id`, `adapter_path`, `state_dir`, and `backlog_path`.
   This step is read-only.
3. **Acquire the repository lease before any shared write.** If the conductor
   supplied a token, verify ownership with `maintenance_lock.py heartbeat` and
   retain it. Otherwise acquire with
   `maintenance_lock.py acquire <state_dir> --loop repo-learn` and record that
   this command owns the returned token. On busy status, stop without changing
   the adapter or state. Once owned, create `state_dir` and persist the identity
   output as `<state_dir>/identity.json`.
4. **Produce** the exact `adapter_path`. Capture architecture and key entry
   points, canonical repository identity, enforced linter/build/test/deploy
   commands (the exact recipe), PR and branch policy, and non-obvious gotchas.
   Every maintenance loop loads this skill first.
5. **Crack the build (HARD GATE):** get one unit test to run **red->green** from an agent-controlled
   checkout and bake the precise recipe into the codebase skill. **No triage-to-action until a test
   runs.**
6. **Verify and release:** ask the codebase skill the repo's enforced build
   command — a wrong answer means it didn't load. Release the lease on every
   exit only when this standalone command acquired it; an inherited conductor
   token remains owned by the conductor.

Done = the helper's `adapter_path` and `identity.json` exist and one test ran
red->green. Hand off to
`/repo-maintenance` or `/maintain-repo` (or an individual loop command).
