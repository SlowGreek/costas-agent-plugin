---
name: costas-agent-guide
description: Explain the installed Costas Agent Plugin, choose the right capability for a task, and teach its operating and safety practices.
user-invocable: true
argument-hint: "[overview|choose|examples|best-practices|troubleshoot] [task]"
---

# Costas Agent Plugin Guide

Explain what this plugin adds, how its skills, rules, hook, and extension work
together, and which capability fits the user's task. This guide does not start
agents, change files, or activate another skill without explicit approval. The
guide itself has no external dependencies.

## When to Use

- "What did this plugin install?"
- "How does this plugin work?"
- "Which skill should I use for this task?"
- "Show me examples and best practices."
- "Why is Goal or Ultracode not working?"

## Prerequisites

- The `costas-agent-plugin` must be installed and enabled in GitHub Copilot CLI.
- Goal continuation requires Python 3 (`python3` on macOS/Linux or `python` in
  the bundled PowerShell hook).
- Ultracode child agents require `GH_TOKEN` in the Copilot CLI environment or a
  working `gh auth login`. `GITHUB_TOKEN` and `COPILOT_GITHUB_TOKEN` do not
  reach the extension process.
- `git` is required only when an Ultracode agent requests a worktree.

## Procedure

1. Interpret the requested mode:
   - `overview`: explain the package layers and capability map.
   - `choose`: recommend a primary capability for the supplied task.
   - `examples`: provide realistic, copy-paste-ready invocations.
   - `best-practices`: explain safe orchestration and completion discipline.
   - `troubleshoot`: identify installation, runtime, authentication, or usage
     problems without hiding errors.
2. If no mode is supplied, give a brief overview and ask what the user wants to
   accomplish. Do not dump every implementation detail.
3. Explain the operating model when relevant:
   - **Skills** are on-demand procedures invoked with slash commands.
   - **Shared rules** apply evidence, isolation, bounded-work, and completion
     standards while the plugin is enabled.
   - The **Goal hook** checks persistent Goal state when a session attempts to
     stop and requests another turn while work and budget remain.
   - The **Ultracode extension** exposes tools for starting and managing bounded
     JavaScript workflows made of isolated Copilot child sessions.
   - Goal and Ultracode runtime state use Copilot plugin-data storage. Workflow
     source files may live in a repository or user workflow directory.
4. Use this capability map:

   | Need | Primary capability | Result |
   | --- | --- | --- |
   | Discover repeated work worth automating | `/loop-design` | Ranked automation candidates from a repo, scoped chats, or both |
   | Continue a long objective across turns | `/goal` | Persistent objective, budget, pause/resume, and completion proof |
   | Run a bounded background agent workflow | `/ultracode` | Persisted multi-agent run with status, cancellation, and resume |
   | Design an adaptive multi-agent approach | `/workflow` | Fan-out, pipeline, adversarial, or repair workflow |
   | Make a high-risk change with independent review | `/adversarial-loop` | Implement-review-fix cycle with evidence gates |
   | Repair compiler, test, runtime, or CI failures | `/failure-work-queue` | Deduplicated, dependency-aware bounded repair queue |
   | Apply a repetitive migration safely | `/mechanical-migration` | Inventory, pilot, shards, and behavior-parity gates |
   | Audit a cross-language port | `/semantic-port-audit` | Semantic mismatch findings and focused regression tests |
   | Turn source material into a reusable procedure | `/learn` | A validated, narrowly scoped `SKILL.md` |
   | Generate ideas systematically | `/creative-ideation` | Ideas produced through named creative methods |
   | Shape a distinctive interface | `/frontend-design` | Intentional visual direction and implementation guidance |

5. Recommend the smallest sufficient mechanism. Use a normal single-agent
   session for small sequential work, a deterministic script or CI job for
   stable transformations, a skill for interactive judgment, and Ultracode only
   when isolated contexts or parallelism add measurable value.
6. For `choose`, return exactly these fields:
   - **Primary capability**
   - **Why**
   - **First command**
   - **Prerequisites**
   - **Bounds and risks**
   - **Completion evidence**
   Name at most two supporting capabilities.
7. For `examples`, tailor invocations to the user's task. Useful patterns
   include:

   ```text
   /loop-design both "recurring CI repair work"
   /goal "Complete the API migration and prove parity" --budget 30
   /workflow "Plan the migration across independent ownership shards"
   /ultracode "Audit every service contract and synthesize the findings"
   /adversarial-loop "Change the authentication lifecycle without regressions"
   /failure-work-queue "Repair the failing test suite"
   /mechanical-migration "Move all callers from API v1 to API v2"
   /semantic-port-audit "Audit the Java-to-Go implementation"
   /learn "Turn this runbook into a reusable incident-response skill"
   /creative-ideation "Generate onboarding concepts for this developer tool"
   /frontend-design "Redesign this settings page"
   ```

8. For `best-practices`, teach this sequence:
   1. Define the complete objective and authoritative completion signal.
   2. Inventory work units before claiming all or every.
   3. Pilot representative units before broad fan-out.
   4. Give parallel writers disjoint files or separate worktrees.
   5. Separate implementer, reviewer, and fixer contexts for risky changes.
   6. Bound agents, concurrency, time, retries, and no-progress rounds.
   7. Treat repeated worker failures as workflow defects, not extra retries.
   8. Stop only on verified completion, an explicit bound, or a genuine external
      blocker.
9. For `troubleshoot`:
   1. Confirm the plugin appears in `copilot plugin list` or `/plugin list`.
   2. After an install or update, start a new session or run `/clear` so skills
      are rescanned.
   3. For Goal failures, check Python availability and plugin-data access.
   4. For Ultracode startup failures, check `GH_TOKEN` or `gh auth token`, then
      inspect the exact run error with `ultracode_status`.
   5. Surface missing prerequisites or inaccessible state. Do not substitute a
      success-shaped fallback.

## Quick Reference

- `/costas-agent-guide overview`
- `/costas-agent-guide choose "<task>"`
- `/costas-agent-guide examples "<task>"`
- `/costas-agent-guide best-practices`
- `/costas-agent-guide troubleshoot "<symptom>"`
- `/loop-design [repo|chats|both] [area or objective]`
- `/goal <objective|status|pause|resume|clear> [--budget N]`
- `/ultracode <task to orchestrate>`
- `/workflow <task>`
- `/adversarial-loop <high-risk task>`
- `/failure-work-queue <failing command or output>`
- `/mechanical-migration <migration>`
- `/semantic-port-audit <source and target>`
- `/learn <source>`
- `/creative-ideation <prompt>`
- `/frontend-design <UI task>`
- `ultracode_start`, `ultracode_status`, `ultracode_wait`
- `ultracode_cancel`, `ultracode_resume`, `ultracode_list`

## Pitfalls

- Do not use multiple agents merely because the tools are available.
- A Goal budget ending is not evidence that the objective is complete.
- Loop Design never silently broadens from repository evidence into unrelated
  chat history.
- Ultracode is read-only by default. Workspace agents need explicit permission
  and non-overlapping ownership or separate worktrees.
- Ultracode children cannot recursively launch task, search-subagent, plugin, or
  Ultracode agent paths.
- Never weaken tests, skip failures, reduce scope silently, or use destructive
  Git shortcuts to make a loop appear complete.
- Plugin components are cached. Reinstall or update the plugin and rescan skills
  before diagnosing unchanged behavior as a code defect.

## Verification

Run `/costas-agent-guide choose "repair recurring CI failures"`. The response
must recommend `/failure-work-queue`, provide a first command, and name an
authoritative completion check without starting work.
