---
name: goal
description: Set a persistent objective that continues across turns until verifiably complete, paused, budget-limited, or strictly blocked.
user-invocable: true
argument-hint: <objective|status|pause|resume|clear> [--budget N]
---

# Goal

Resolve this skill's plugin root from the skill context. Manage state with:

```bash
python3 <PLUGIN_ROOT>/runtime/goalctl.py set "<objective>" --budget 30
python3 <PLUGIN_ROOT>/runtime/goalctl.py get
python3 <PLUGIN_ROOT>/runtime/goalctl.py edit "<objective>"
python3 <PLUGIN_ROOT>/runtime/goalctl.py pause
python3 <PLUGIN_ROOT>/runtime/goalctl.py resume
python3 <PLUGIN_ROOT>/runtime/goalctl.py complete
python3 <PLUGIN_ROOT>/runtime/goalctl.py block --reason "<same external blocker>"
python3 <PLUGIN_ROOT>/runtime/goalctl.py clear
```

The default continuation budget is 30 and the hard cap is 100. Keep the whole
objective intact. Before completion, derive every requirement and prove it
against current files, command output, or tests. Mark blocked only when the same
external blocker has persisted for at least three consecutive goal turns and
user input or an external change is genuinely required. Budget exhaustion
allows one wrap-up turn and is not proof of completion.
