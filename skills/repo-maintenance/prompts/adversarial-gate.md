# Prompt template — adversarial gate (3 refuting lenses)

The verifier that makes a maker's "it's done" mean something. Before a fix ships, three **independent**
skeptics attack it from distinct angles with a mandate to **refute**, not bless. Required for any
stateful / data-source / migration / upgrade-path change — a passing build is not sufficient
validation for those. Run the three in parallel; the reviewer is never the agent that wrote the code.

This is best run as a workflow (one agent per lens, fan out, collect verdicts). Fill the `{...}`
placeholders. The companion gate it pairs with is `wi-fidelity.md` (does it fix the *filed* bug);
this gate asks whether the fix is *correct and safe*.

---

The three lenses (spawn one agent each, all read-only):

```
FIRST load the {REPO} codebase skill. Read-only: do not edit/build/push.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.
You are an ADVERSARIAL reviewer of the change on branch {BRANCH} for {WI_ID}: {ONE_LINE_SUMMARY}.
MANDATE: REFUTE this fix. Assume it is wrong or incomplete and hunt for the specific defect — do NOT
bless it. Default to skepticism; only return SOLID if, after a genuine attempt, you cannot break it.
Get the diff: `git fetch` then `git diff {BASE}...{BRANCH}` (read the changed files + tests fully,
and any consumer the change affects).

YOUR LENS — {LENS}:
  • correctness     → Find a real correctness bug. Edge inputs, nulls, ordering, concurrency, the
                      migration/upgrade path, data-loss, the wrong-of-two-duplicate-paths, an
                      over-/under-exclusion. Give the exact input/scenario that breaks it.
  • test-validity   → Attack the TEST. Does it drive the REAL path (not a hand-rolled helper or a
                      mock artifact)? Does it FAIL red against the unmodified code? Does it cover the
                      branches that matter? Would it pass against base (i.e. prove nothing)?
  • edge/security   → Missed edge case, injection, secret/PII in logs, auth/permission gap, resource
                      exhaustion, a torn/partial state an observer can see.

Be concrete: if you claim a PROBLEM, give the exact repro (input → expected vs actual).
Return: verdict (SOLID | PROBLEM), severity, finding (the specific defect + repro, or a one-line
why-it's-solid). Set lens="{LENS}", wi="{WI_ID}".
```

Decision rule (orchestrator): collect the three verdicts. **Any PROBLEM at medium+ severity sends
the change back to the maker** with the finding. All SOLID → it proceeds to the WI-fidelity gate.
For higher assurance on risky changes, run N>1 refuters per lens and require a majority-SOLID.

---

## Why
A green build passes data-loss, torn-snapshot, wrong-path, over-exclusion, and migration-gap bugs
that the unit test never exercised. Three *diverse* lenses (not three identical refuters) catch
failure modes redundancy can't. The split of verifier from maker is what lets "done" mean something.
