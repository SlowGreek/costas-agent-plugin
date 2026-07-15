# Repository maintenance harness

This directory is the shared runtime library for the Costas Agent Plugin's
repository-maintenance commands. It turns a repository into a gated maintenance
system: onboard once, then triage, implement, steward PRs, review changes,
monitor dependencies and CI, verify merged fixes, report outcomes, and improve
the harness from evidence.

## General, but adaptive

- **The harness is repository-neutral.** `SKILL.md`, `DESIGN.md`, and `prompts/`
  define the disposition taxonomy, verifier stack, authority boundaries, and
  standing-loop contracts.
- **`/repo-learn` generates the codebase adapter.** It records the target
  repository's architecture, conventions, exact build/test recipe, branch
  policy, and gotchas in `<repo>-codebase`.
- **`/custom-pr-review` generates the review adapter.** It mines demonstrated
  reviewer behavior into a repository-specific review profile.

Switching repositories means regenerating those adapters, not forking the
harness.

## Commands

| Command | Purpose |
|---|---|
| `/repo-maintenance`, `/maintain-repo` | Run the full conductor |
| `/repo-learn` | Create and prove the codebase adapter |
| `/repo-triage` | Classify actionable backlog items with evidence |
| `/repo-implement` | Submit authorized gated drafts or prepare drainable handoffs |
| `/repo-pr-maintenance` | Reconcile active PRs, CI, and review threads |
| `/repo-auto-review` | Submit authorized defect WIs or prepare them |
| `/custom-pr-review` | Learn and apply team review standards |
| `/repo-dep-sweep` | Submit authorized dependency WIs or prepare them |
| `/repo-ci-health` | Submit authorized or prepare de-flake/quarantine artifacts |
| `/repo-post-merge` | Verify landed fixes; submit or prepare regression artifacts |
| `/repo-report` | Produce a concise evidence-linked maintenance report |
| `/repo-self-improve` | Submit authorized or prepare self-improve WI/draft pairs |

## Shared resources

```text
repo-maintenance/
  SKILL.md
  HARNESS-COPILOT.md
  DESIGN.md
  prompts/
  bundled/
    learn.md
    goal-loop.md
  runtime/
    maintenance_lock.py
    repo_identity.py
  review-profile.template.md
```

Standalone command skills resolve these resources relative to their own
installed directories. No personal installation path is required.

## Prerequisites

- Issue, PR, review-thread, and CI access for the repository host. GitHub and
  Azure DevOps are supported when their corresponding tools are available.
- Bundled `/goal`, `/workflow`, and `/ultracode` capabilities.
- Python 3 for the cross-process repository execution lease. The lease
  serializes Goal and backlog mutations across overlapping workflow fires.
- `save_workflow`, `run_workflow`, and `list_workflows` for persistent standing
  mode. Without them, commands remain usable on demand but the system is not
  armed.
- Explicit landing/push authority and an escalation boundary.

## Installation and quick start

The harness is installed with the Costas Agent Plugin; do not copy this folder
or its bundled recipes separately.

1. Run `/repo-learn` in the target repository and prove one test red-to-green.
2. Run `/repo-maintenance` or its exact alias `/maintain-repo`.
3. Confirm the proposed authority mode and escalation boundary.
4. Require all supported workflows to be enabled and proof-fire at least one
   before considering the system armed.

Every code change remains behind the shared verifier stack and a draft PR.
Missing scheduler or provider capabilities must be reported explicitly, never
treated as a successful setup.
