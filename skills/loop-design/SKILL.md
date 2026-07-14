---
name: loop-design
description: Inspect a repository and/or scoped agent-session history read-only, rank recurring engineering work suitable for automation, and generate a selected loop only after approval.
user-invocable: true
argument-hint: "[repo|chats|both] [area or objective]"
---

# Loop Design

Do not change code during inventory or proposal. Treat repositories and session
history as read-only evidence.

## Source selection

1. Accept one source mode:
   - `repo`: inspect only the repository.
   - `chats`: inspect the current conversation and available agent-session
     history.
   - `both`: inspect both and corroborate patterns across them.
2. If the user did not select a mode, ask before reading historical chats. Do
   not silently expand from repository inspection into session history.
3. Scope chat history to the current repository, workspace, or project by
   default. State the scope and time window. Require explicit approval before
   inspecting unrelated repositories, projects, or global history.
4. Use structured session-history tools when available. Query metadata,
   summaries, checkpoints, touched files, and references before reading
   individual turns. Start with a bounded recent window and widen it only when
   the initial sample is too sparse.
5. If requested history is unavailable, report that limitation and ask whether
   to continue with repository evidence or user-provided transcripts. Do not
   claim that repository evidence represents chat recurrence.

## Session-history inventory

When the mode includes `chats`:

1. Identify repeated user intents, manual repair sequences, recurring failures,
   repeated tool chains, review feedback, handoff friction, and follow-up work
   that repeatedly survives a session boundary.
2. Count recurrence across distinct sessions, not repeated turns within one
   conversation. Record the sampled time range and session count so frequency
   estimates remain auditable.
3. Inspect turn bodies only for sessions relevant to a candidate. Separate a
   recurring engineering need from repeated agent mistakes that should instead
   be fixed at their source.
4. Capture successful completion signals as well as pain points. A repeated
   prompt is not automatable until there is a reliable way to determine that
   its work is complete.
5. Cite session title or identifier and date with the minimum excerpt needed.
   Summarize patterns; do not persist raw transcripts in the repository or in
   generated automation.
6. Exclude credentials, tokens, personal content, and unrelated conversations
   from evidence and output. Respect access controls and content exclusions;
   never work around unavailable history.

## Repository inventory

When the mode includes `repo`:

1. Identify repository roots, local instructions, languages, package managers,
   and ownership boundaries.
2. Inspect CI workflows; package/build/test/lint/typecheck scripts; compiler and
   linter configuration; issue and pull-request templates; generators,
   migrations, fixtures, snapshots, schemas, and repeated file families.
3. Inspect review, security, dependency, fuzz, release, localization, and
   documentation processes.
4. Cite concrete paths and commands. Distinguish observed evidence from
   assumptions.
5. Cluster recurring work by trigger and authoritative completion signal.

## Evidence synthesis

In `both` mode, connect chat-reported friction to repository paths, commands,
owners, and completion signals. Label candidates supported by only one source
and lower their confidence rather than inventing corroboration. Chat evidence
strengthens observed recurrence; repository evidence grounds feasibility.
Either source may reveal a candidate, but every recommendation still needs a
bounded work unit and an authoritative stop condition.

## Candidate record

For every candidate provide:

- source scope, sample window, and confidence
- observed evidence: repository paths and commands and/or minimal session
  references
- trigger
- work unit and inventory method
- workflow pattern
- prerequisites and shared artifacts
- implementer, reviewer, and fixer roles
- isolation/sharding and merge strategy
- authoritative stop condition
- resource, security, and concurrency risks
- expected value and observed or estimated frequency
- recommended form: direct automation, Ultracode workflow, skill, or CI

Rank by `(frequency × saved effort × reliability × measurability) / risk`.

## Anti-overautomation rubric

Reject candidates that are rare, unsafe to run unattended, lack a stable work
unit, lack a machine-checkable stop condition, need frequent subjective
judgment, duplicate a deterministic script, or cost more to supervise than they
save. Prefer direct scripts/CI for deterministic transformations. Use a skill
for interactive judgment and Ultracode only when isolated model contexts add
measurable value.

Present the source coverage and ranked portfolio, then ask which candidate to
implement. Only after explicit approval may you generate the selected workflow,
skill, automation, or CI change. Preserve the approved trigger, bounds,
ownership, stop condition, privacy constraints, and rollback strategy.
