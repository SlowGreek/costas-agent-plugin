# Repository onboarding recipe

This recipe is consumed by `/repo-learn`. It creates the repository-specific
adapter required by every maintenance loop.

## 1. Establish scope and rules

Use the current working directory's Git repository as the target. Read the root
and area-specific agent instructions before inspecting or changing code.

Resolve the installed `repo-maintenance` skill directory and run:

```bash
python3 <repo-maintenance-dir>/runtime/repo_identity.py --cwd <repo-root>
```

Use its output verbatim:

- `repo_id` is `<repo>` everywhere in this harness;
- `adapter_path` is the codebase skill file;
- `state_dir` is `<triage-dir>` and the one lease root shared by all worktrees;
- `backlog_path` is the authoritative maintenance backlog.

The helper uses a bounded readable prefix plus a hash of the canonical remote
(or common Git directory when no remote exists), so names are unique and remain
within Copilot's skill-name limit. Identity resolution is read-only. Before
creating `state_dir`, `identity.json`, or the adapter, acquire the repository
lease described in `HARNESS-COPILOT.md` (or verify an inherited conductor token).
Only the lease owner may create `state_dir` and retain the output as
`identity.json`. Do not independently recompute or shorten these values.

## 2. Inventory the codebase

Use code intelligence, `glob`, `rg`, and focused file reads to identify:

- architecture, major packages, entry points, and dependency boundaries;
- language and package manifests;
- exact format, lint, build, test, and deploy commands already defined by the
  repository;
- test layout, fixtures, and the smallest selectable unit-test command;
- branch, pull-request, ownership, security, and release policies;
- generated or ignored outputs and non-obvious local prerequisites.

Do not infer commands from ecosystem convention when a repository-owned command
exists. Do not install new tooling merely to make onboarding easier.

## 3. Author the codebase skill

Write the helper's exact `adapter_path` with:

```markdown
---
name: <repo>-codebase
description: Apply the target repository's architecture, conventions, and proven build/test workflow.
user-invocable: false
---

# <Repo> codebase

## Architecture
## Repository identity
## Development workflow
## Build and test
## Pull-request and release policy
## Gotchas
## Verification
```

Keep the skill concise and factual. Include exact working-directory assumptions,
commands, selectors, and expected outputs. Put bulky reference material in
sibling files and link to it.

## 4. Crack the build

This is a hard gate before maintenance can arm:

1. Select the smallest representative unit test.
2. Run it unchanged and capture the passing baseline.
3. Make a temporary, controlled change that causes that exact test to fail.
4. Restore the source precisely.
5. Re-run the same test and confirm it passes.
6. Record the complete red-to-green command sequence in the codebase skill.

Never weaken, skip, or delete a test to satisfy this gate. Remove every temporary
change and generated scratch artifact.

## 5. Verify the adapter

- Confirm the skill exists at
  the helper's `adapter_path`.
- Confirm its recorded remote/root identity matches the current repository.
- Confirm `<triage-dir>/identity.json` matches a fresh helper invocation from
  every worktree that will run maintenance.
- Re-read it and verify every command appears in the repository's own scripts or
  documentation.
- Ask the loaded skill for the enforced build command and compare the answer
  with the source manifest.
- Confirm the working tree contains no onboarding-only edits.

Completion requires both a valid codebase skill and a proven red-to-green test
recipe. If either is missing, report the blocker and do not arm maintenance
loops.
