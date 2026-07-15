# Team Review Profile — TEMPLATE / SCHEMA

> The durable, learned artifact the `pr-review` loop produces and refreshes. The **live** copy lives
> per-repo in the triage-dir (e.g. `<triage-dir>/review-profile.md`) — it is a per-repo *adapter*
> (like the codebase skill), not part of the shared harness. This file is the template + schema.
>
> It captures the team's **demonstrated** review standards (what reviewers actually enforce, what makes
> a PR merge vs. bounce), each rule backed by evidence from real merged PRs. It is **advisory** — the
> reviewer never blocks a PR or posts a comment without escalation. Human-readable on purpose: prune,
> edit, and **pin** rules freely.

## Config
```
repo:               {REPO} (ADO/GitHub id)
default_branch:     {DEFAULT_BRANCH}
scope:              our-draft-PRs-only        # | all-open-team-PRs | both   (asked at setup; default: our-draft-PRs-only)
corpus_N:           100                        # most-recently-merged PRs to learn from
refresh_cadence:    weekly
trusted_reviewers:  []                         # optional: names whose comments weigh most
last_refresh:       <date>                     # set by Refresh; the initial LEARN seeds it = synthesis date
merged_pr_cursor:   <provider cursor/date>     # style-exemplar delta only
review_comment_cursors_by_pr:                  # immutable-PR-id -> last successfully processed comment cursor
  <provider-immutable-pr-id>: <provider cursor/date>
review_comment_scan_high_watermark: <provider event id/date> # scan-start bound; never an aggregate cursor
review_comment_scan_snapshot: [<provider-immutable-pr-id>]   # exact PR set captured at scan start
review_comment_scan_pending_prs: [<provider-immutable-pr-id>] # snapshot PRs not yet processed or
  # dispositioned this scan; a non-empty set means the scan is INCOMPLETE and must be resumed against
  # this SAME snapshot/high-watermark before the next refresh captures a new one. A PR leaves this set
  # only once processed, or explicitly dispositioned with provider evidence (e.g. closed/merged/unmerged mid-scan).
open_prs_polled_at: <date>                     # proves the scan snapshot was checked
```

## Pinned rules (human-set — SACROSANCT, never auto-dropped/overridden)
> Rules a human explicitly pins. Autonomous refresh must preserve these verbatim. The codebase skill's
> documented conventions are implicitly pinned too.
- _(none yet)_

## Learned rules
> One row per rule. `must-fix` rules are the ones reviewers reliably block on; `nit` rules are
> frequently-mentioned preferences; `signal` rows are behavioral/merge-shape observations (vote-gating,
> fast-merge vs multi-round) that aren't a fix/nit. `evidence` ties every rule to the PRs/comments it
> came from — a rule with no evidence is not a real convention and must be dropped.

### Axis: Tests & coverage
| rule | must-fix? | evidence (PRs / quotes) | freq/conf | pinned |
|------|-----------|-------------------------|-----------|--------|
| _e.g._ New behavior ships with a red-first unit test on the real path | must-fix | #NNNN "use TDD"; #NNNN "add a non-working-hours test" | high | no |

### Axis: Naming & structure
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|

### Axis: Scope & size
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|
| _e.g._ Prefer the smallest reviewable diff; surface larger refactors as an option, don't bundle them | nit | #NNNN "huge/hacky — prefer the 10-liner" | med | no |

### Axis: Error-handling & null-safety
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|

### Axis: API / Graph usage
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|

### Axis: PR description & docs
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|
| _e.g._ Cite the WI's recorded scope decisions proactively in the PR body | nit | #NNNN "document out-of-scope before a human asks" | med | no |

### Axis: Approver expectations
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|

### Axis: Fast-merge vs. bounce signals
| rule | must-fix? | evidence | freq/conf | pinned |
|------|-----------|----------|-----------|--------|

## CHANGELOG (append-only — every Refresh writes a dated block)
> Makes fully-autonomous learning auditable. Each entry: what changed and the PRs that drove it.
- **<date> — initial profile.** Learned from the {N} most-recently-merged PRs (corpus: human comments
  from all PRs incl. bot PRs; style exemplars from human-authored PRs only). N rules across M axes.
