---
name: ultracode
description: Use when a large task benefits from a dynamic JavaScript workflow that can fan out isolated Copilot sub-agents, coordinate bounded parallel or adversarial work, and persist synthesized results.
user-invocable: true
argument-hint: <task to orchestrate>
---

# Ultracode

Use Ultracode for large, parallel, iterative, or adversarial work that benefits
from isolated contexts. Do not use it for a small sequential task.

## Procedure

1. Preserve the full objective and define evidence that proves completion.
2. Inventory the work units and externalize shared invariants.
3. Choose a bounded pattern: classify-and-act, fan-out-and-synthesize,
   adversarial verification, generate-and-filter, tournament, or
   loop-until-done.
4. Pilot 2–3 representative units. Repair the workflow when failures are
   systematic.
5. Present estimated agents, concurrency, permission mode, timeout, worktrees,
   and stop condition before starting.
6. Write a JavaScript workflow in the current repository or user workflows
   directory. It may use `agent()`, `pipeline()`, `args`, and standard
   JavaScript. Imports and dynamic code generation are unavailable.
7. Call `ultracode_start`, then use status/wait/cancel/resume/list.
8. Report completion only when inventory counts match and status is completed
   with no running or failed agents.

## API

```js
const audits = await pipeline(args.files, (file) =>
  agent(`Audit ${file}; cite concrete evidence.`, {
    label: file,
    schema: {
      type: "object",
      required: ["findings"],
      properties: {
        findings: { type: "array", items: { type: "string" } },
      },
    },
  }),
)
return audits
```

`agent()` options include `label`, `model`, `schema`, `timeoutMinutes`, and
`worktree` (`true` or a path). `read-only` is the default permission mode.
`workspace` can modify files and must use disjoint ownership or worktrees.

Direct `agent()` calls are capped by `maxAgents`. Child sessions cannot call
`task`, `search_code_subagent`, or Ultracode recursively.
