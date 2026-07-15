#!/usr/bin/env python3
"""Fail-open agentStop continuation hook for the /goal skill."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import goalctl


def continuation_reason(objective: str, used: int, cap: int) -> str:
    goalctl_path = os.environ.get("GOALCTL_PATH", "goalctl.py")
    return (
        "Continue working toward the active goal. Keep the full objective intact "
        "and work from current evidence.\n\n"
        f"<objective>\n{objective}\n</objective>\n\n"
        "Before completion, audit every requirement and prove it against current "
        "files, command output, or tests. Mark complete only when that audit passes:\n"
        f'  python3 "{goalctl_path}" complete\n'
        "Only a genuinely external blocker may stop the loop. The same blocker must "
        "survive three consecutive goal turns; record it with:\n"
        f'  python3 "{goalctl_path}" block --reason "<stable blocker>"\n'
        f"[goal continuation {used} of {cap}]"
    )


def budget_reason(objective: str, used: int) -> str:
    goalctl_path = os.environ.get("GOALCTL_PATH", "goalctl.py")
    return (
        "The active goal reached its continuation budget. Do not start new "
        "substantive work. Use this one wrap-up turn to report proven progress, "
        "remaining work, blockers, and the next action.\n\n"
        f"<objective>\n{objective}\n</objective>\n\n"
        f"Forced continuations used: {used}. Mark complete only if proven:\n"
        f'  python3 "{goalctl_path}" complete'
    )


def block(reason: str) -> None:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}))


def parse_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def hook_session_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("sessionId")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def hook_cwd(payload: dict[str, Any]) -> str | None:
    value = payload.get("cwd")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def main() -> None:
    try:
        payload = parse_payload()
        session_id = hook_session_id(payload)
        if session_id is None:
            return
        cwd = hook_cwd(payload)
        if cwd is None:
            return
        # The hook's session id comes from the stop payload, not a verified root
        # claim, so it must never trigger the v1.0 legacy-state migration (that
        # would let a child's stop event single-winner-steal a goal that isn't
        # provably its own). Read this session's own scoped slot only.
        state = goalctl.load_without_legacy_claim(cwd, session_id)
        if not isinstance(state, dict) or state.get("status") != "active":
            return
        objective = str(state.get("objective") or "").strip()
        if not objective:
            return
        used = int(state.get("continuations") or 0)
        configured = state.get("budget_turns")
        budget = goalctl.DEFAULT_BUDGET_TURNS if configured is None else int(configured)
        cap = max(1, min(budget, goalctl.HARD_CAP))
        if used >= cap:
            state["status"] = "budget_limited"
            goalctl.save(state, cwd, session_id)
            block(budget_reason(objective, used))
            return
        state["continuations"] = used + 1
        goalctl.save(state, cwd, session_id)
        block(continuation_reason(objective, used + 1, cap))
    except Exception:
        # No output means allow stop. A hook failure must never trap a session.
        return


if __name__ == "__main__":
    main()
