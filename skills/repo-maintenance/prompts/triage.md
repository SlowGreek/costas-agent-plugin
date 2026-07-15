# Prompt template — backlog triage (disposition with proof)

Dispatch template for the **Triage loop**. Classifies untriaged backlog items into exactly one
disposition, each with its **required artifact**. Read-mostly: it may write a repro test to run the
staleness gate (code-only; the orchestrator runs the build), but it does not implement fixes. Fill
the `{...}` placeholders. Full taxonomy + rationale: `DESIGN.md` §3.

---

```
FIRST load the {REPO} codebase skill (SKILL.md + architecture). You are triaging, not fixing — do
NOT implement a fix or open a PR. If you need to run a test to prove staleness, write it (code-only)
and hand the orchestrator the recipe.
GOAL GUARD: you are a dispatched sub-agent — NEVER run `/goal` or `goalctl.py`; your tool shell
inherits the ROOT orchestrator's session id, so a Goal mutation would hijack the orchestrator's goal.

For each item below, work the decision tree IN ORDER and stop at the first disposition that fits.
Attach the REQUIRED ARTIFACT — a disposition without its artifact is a guess, not a triage.

ITEMS:
{ITEMS: id + title + repro/description, one per line}

DECISION TREE (per item):
1. STALENESS GATE (first, always). Write a repro test that exercises the item's real scenario and
   would FAIL red on the described broken path. If, against the current integrated target, it would PASS pre-fix →
   the item is already fixed:
       → disposition = OUTDATED.  ARTIFACT = the passing-on-target repro test (proof). STOP.
2. FEASIBILITY / DATA-EXISTENCE. Does the data or signal the fix would depend on actually EXIST in
   the real production pipeline (not just constructible by hand in a test)? Check the real source
   (the query/field/event), not a fixture. If the signal does not exist (no such flag, an unwired
   control, a query that strips the very record the logic needs):
       → disposition = NOT-ACTIONABLE (or NEEDS-DECISION if a product/data-model change could add
         it).  ARTIFACT = the why, with file:line showing the signal is absent. STOP.
3. OWNERSHIP. Is the behavior owned by THIS repo's code, or by another system (OS/platform settings,
   a different service, a vendor component this repo only deep-links into)? If not owned here:
       → disposition = NOT-ACTIONABLE.  ARTIFACT = name the system that owns it. STOP.
4. VERIFIABILITY. Can a headless logic/unit test assert the fix, or is the load-bearing behavior a
   rendered layout / device-setting read / visual that only a device/emulator can verify?
       → device/visual only → disposition = NEEDS-QA.  ARTIFACT = the exact on-device/visual check a
         human must run. Do NOT touch the code. STOP.
5. BOUNDEDNESS. Is a bounded code change enough, or does the right fix need a product call or a
   larger cross-cutting refactor?
       → needs a decision/large change → disposition = NEEDS-DECISION.  ARTIFACT = the specific
         product/architecture question. STOP.
6. Otherwise → disposition = VERIFIABLE. It enters the Implement loop. ARTIFACT = a one-line note of
   the real broken path the repro test will pin.

OUTPUT (per item): id · disposition · the required artifact · one-line rationale. Where you wrote a
staleness repro test, include it + the recipe so the orchestrator can run it red/green.
Be conservative: most of a stale backlog is OUTDATED / NOT-ACTIONABLE / NEEDS-QA. Reporting those
faithfully WITH their artifact is the correct result, not a failure to find work.
```

---

## Notes
- The staleness gate is first because backlogs accrete faster than they close — assume an item is
  already fixed until a red test proves otherwise.
- The feasibility check (step 2) is the defense against the "wrong/absent data signal" failure: a
  fix that's green against a hand-built fixture but inert in production because the signal isn't real.
- `NEEDS-QA` / `NEEDS-DECISION` items are handed to the human with their artifact; the loop does not
  touch their code.
