# Prompt template — learned team-style PR reviewer (the `pr-review` loop)

Dispatch template for the **pr-review loop**: a reviewer that learns the team's *demonstrated* review
standards from merged PRs and applies them as an **evidence-based, advisory** review layer. It is the
*learned* counterpart to the static "style review against the codebase skill" gate — it captures what
reviewers actually enforce in practice and what makes a PR merge vs. bounce. Two modes: **LEARN**
(build/refresh the profile) and **REVIEW** (apply it to a PR). Fill the `{...}` placeholders.

**Invariants (all modes — load-bearing):**
- **Advisory, never blocking.** Prepare-and-escalate; **never auto-post** a comment outward.
- **Learn/review against the DEFAULT branch** (merged PRs / PRs targeting it) — never un-merged
  working-branch-only state.
- **Echo-chamber guard.** Never mine our own `ai/wi-*` bot PRs' **diffs** as style exemplars; DO mine
  humans' **comments** on them.
- **Taste & convention only** — NOT security / correctness / WI-fidelity / lint (those are other gates).

---

## LEARN mode

```
FIRST load the {REPO} codebase skill. You are building/refreshing the team review profile at
{PROFILE_PATH}. Read-only against the repo; the ONLY file you write is the profile.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

CORPUS — two distinct sources (do NOT conflate them):
  • STYLE-EXEMPLAR corpus → the {N=100} most-recently-MERGED, HUMAN-authored PRs into {DEFAULT_BRANCH}.
    Merged + human = the team's accepted code. Mine diff/structure patterns here.
  • PREFERENCE/ASK corpus → human REVIEW COMMENTS across PRs — merged AND **open/active** — INCLUDING
    humans' comments on our own open `ai/wi-*` bot PRs. (Our bot PRs often sit in DRAFT and rarely
    merge, so the richest "humans correcting the machine" signal lives on OPEN drafts, not the merged
    set — a merged-only corpus misses it entirely.)
Fan out via the Workflow tool — one agent per PR (or per small batch). For each PR extract: every human
review comment + how it resolved (changed / won't-fix + reason); merge shape (# review cycles,
fast-merge vs many-rounds, who approved); conventions enforced IN REVIEW but not by lint/CI;
change-request ("bounce") triggers; test/coverage expectations voiced in review.

DISTINGUISH THREE COMMENT SOURCES (don't blur them):
  • HUMAN reviewers → the real preference signal. Weight by engagement; if {TRUSTED_REVIEWERS} is set,
    weight them most.
  • An automated AI code-review bot (e.g. GitOps "PR Assistant" / `pullrequestcopilot`) → treat as
    **automated, lint-like findings** (ratified-or-not by humans), NOT human preference. Strip its HTML
    boilerplate down to the finding text (it is ~95% template noise — critical for cost at N=100).
  • Our own `ai/wi-*` PR authorship → a PR *origin* distinction, not a comment source.

THE ECHO-CHAMBER SPLIT (the whole point):
  • PREFERENCES / ASKS  → from human comments across the PREFERENCE corpus above (incl. humans' comments
    on our open bot PRs — highest-value, zero echo risk).
  • STYLE EXEMPLARS     → from the STYLE-EXEMPLAR corpus only (merged, human-authored). NEVER treat our
    bot PRs' diffs as "good examples" — that is the echo chamber.

SYNTHESIZE → write {PROFILE_PATH} (see the review-profile template). Each rule carries:
  - statement (imperative, specific),
  - must-fix | nit | signal   (signal = a behavioral/merge-shape observation — vote-gating, fast-merge
    vs multi-round, auto-complete — that isn't a fix or a nit),
  - evidence: the source PR#s / short comment quotes it was derived from,
  - frequency / confidence,
  - pinned? — PRESERVE every existing pinned rule verbatim; NEVER drop or override a pinned rule or a
    documented codebase-skill convention.
  Group by axis: tests · naming/structure · scope/size · error-handling · API/Graph usage ·
  PR-description/doc norms · approver expectations · fast-merge-vs-bounce.

REFRESH (when the profile already exists): keep the STYLE cursor separate, then make COMMENT refresh
race-safe AND resumable:
  • **Resume before capturing anything new.** If a persisted {REVIEW_COMMENT_SCAN_SNAPSHOT} /
    {REVIEW_COMMENT_SCAN_HIGH_WATERMARK} exists with a non-empty {REVIEW_COMMENT_SCAN_PENDING_PRS} set,
    that prior scan is INCOMPLETE — drain it first: retry each pending immutable PR id against the SAME
    persisted snapshot/high-watermark until it is either successfully processed (its comments polled,
    its cursor advanced, removed from the pending set) or explicitly dispositioned with provider evidence
    (closed/merged/deleted — record the provider's own status + timestamp as proof) before removing it
    from the pending set. Only once the prior snapshot's pending set is fully drained does refresh
    proceed to capture a NEW snapshot.
  • STYLE cursor — ingest human-authored PRs merged since {LAST_MERGED_PR_CURSOR}.
  • At scan start (once any prior scan is drained), capture the NEXT {REVIEW_COMMENT_SCAN_SNAPSHOT}:
    immutable ids for every currently open PR plus the selected recently merged PRs, and capture one
    provider {REVIEW_COMMENT_SCAN_HIGH_WATERMARK}. Seed {REVIEW_COMMENT_SCAN_PENDING_PRS} with that
    exact snapshot. Do not extend this snapshot mid-scan.
  • COMMENT cursors — for each immutable PR id in the snapshot, poll human review comments newer than
    {REVIEW_COMMENT_CURSORS_BY_PR[immutable_pr_id]} and <= the scan high-watermark. Process that PR's
    events, then and only then advance **that PR's** cursor and remove it from the pending set. A
    failed or inaccessible PR (rate limit, transient provider error, permission gap) STAYS in the
    pending set — never dropped silently — and is retried on this and every later refresh until it is
    processed or explicitly dispositioned with provider evidence. **A PR that closes or unmerges
    mid-scan must not silently drop its comments**: fetch its final state, record the closure/unmerge
    as its disposition evidence, harvest any comments still readable up to that state, then remove it
    from the pending set. Comments after the high-watermark and PRs absent from the snapshot wait for
    the next refresh. Open drafts remain in every snapshot because new comments arrive without a merge.
Persist the snapshot, high-watermark, and pending set alongside the per-PR cursor map after every PR's
outcome — not only at the end — so a crash mid-scan leaves an accurate, resumable pending set. Merge
the successful deltas into the profile and advance the STYLE cursor only after its source was processed
successfully. APPEND a dated CHANGELOG block (rules
added/changed/removed + why). Fully autonomous — no approval gate — but the
CHANGELOG makes every change auditable/vetoable after the fact, and pinned /
codebase-skill rules are sacrosanct. If neither source yields a new rule after
dedup, log a DRY learning round and stop.

OUTPUT: the updated profile path + a short summary of what changed (for the weekly report digest).
```

## REVIEW mode

```
FIRST load the {REPO} codebase skill AND {PROFILE_PATH}. Read-only: you PREPARE findings — you do NOT
post them and you do NOT edit code.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

TARGET ({PR_SCOPE}, chosen at loop setup):
  • our-draft-PRs-only  (DEFAULT) → our open ai/wi-* draft PRs only.
  • all-open-team-PRs            → every open PR, teammates' included.
  • both.

Apply {PROFILE_PATH} to the target PR's diff (pulling it via `get_changes` with line content is heavy
on large files — scope it / prefer an iteration compare when the file is big). Emit FINDINGS, each:
  - the profile rule it matches/violates,
  - must-fix | nit,
  - evidence: "your team asked for this in PRs #X/#Y" (cite the rule's sources),
  - a concrete, specific suggestion.
Raise taste & convention only — NO security / correctness / WI-fidelity / lint findings (other gates
own those). If the PR is clean against the profile, say so plainly.

ROUTING (prepare-and-escalate — NEVER auto-post):
  • our PRs  → hand the findings to the implement / pr-maintenance gate as an ADVISORY input. It does
    NOT block the PR; it informs the prepare-and-escalate decision.
  • others   → prepare draft comments and ESCALATE to {HUMAN} for approval BEFORE anything is posted.

OUTPUT: the findings list (or "clean against profile"); for non-our PRs, the prepared-but-unposted
comments.
```

---

## Why each clause is here
- **Learn from MERGED PRs against the default branch** — merged = the team accepted it, and it's
  target-grounded by construction, so the reviewer never learns from (or reviews) dead working-branch-only
  code. (Cf. a false-find where a sweep hit working-branch-only code never present on the target branch.)
- **The echo-chamber split** — humans' comments on our bot PRs are the single best alignment signal and
  carry no circularity; treating our bot's own diffs as "exemplars" would be the system praising itself.
- **Evidence on every rule and finding** — a learned standard you can't trace to real PRs is a
  hallucinated convention. Citations make the profile auditable and prunable by a human.
- **Advisory + prepare-and-escalate** — taste is subjective and outward comments are irreversible; the
  human stays in the loop (escalation boundary, `DESIGN.md` §9).
- **Pinned + codebase-skill rules sacrosanct** — the guardrail that keeps fully-autonomous weekly
  learning from drifting away from explicit human intent.
- **Taste only, not security/correctness/lint** — those have dedicated gates; conflating them dilutes
  both and produces noisy reviews.
