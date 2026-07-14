#!/usr/bin/env python3
"""Portable per-worktree state controller for the /goal skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any

STATUSES = ("active", "paused", "blocked", "budget_limited", "complete")
DEFAULT_BUDGET_TURNS = 30
HARD_CAP = 100
PLUGIN_NAME = "costas-agent-plugin"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def goals_dir() -> Path:
    explicit = os.environ.get("GOAL_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    plugin_data = os.environ.get("COPILOT_PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data).expanduser() / "goals"

    plugin_root = Path(__file__).resolve().parent.parent
    installed_plugins = plugin_root.parent.parent
    if installed_plugins.name == "installed-plugins":
        copilot_home = installed_plugins.parent
        marketplace = plugin_root.parent.name
        return copilot_home / "plugin-data" / marketplace / plugin_root.name / "goals"

    copilot_home = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot")).expanduser()
    return copilot_home / "plugin-data" / "_direct" / PLUGIN_NAME / "goals"


def key_for_cwd(cwd: str | os.PathLike[str]) -> tuple[str, str]:
    real = os.path.realpath(os.fspath(cwd))
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16], real


def state_path(cwd: str | os.PathLike[str] | None = None) -> Path:
    key, _ = key_for_cwd(cwd or os.getcwd())
    return goals_dir() / f"{key}.json"


def load(cwd: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    try:
        value = json.loads(state_path(cwd).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save(state: dict[str, Any], cwd: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    directory = goals_dir()
    directory.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    destination = state_path(cwd)
    staging = destination.with_name(f"{destination.name}.{os.getpid()}.pending")
    staging.write_text(f"{json.dumps(state, indent=2)}\n", encoding="utf-8")
    os.replace(staging, destination)
    return state


def reset_blocker_audit(state: dict[str, Any]) -> None:
    state["blocker_signature"] = None
    state["blocker_turns"] = 0
    state["blocker_last_continuation"] = None


def cmd_set(args: argparse.Namespace) -> int:
    objective = args.objective.strip()
    if not objective:
        print("objective must not be empty", file=sys.stderr)
        return 2
    budget = args.budget
    if budget is not None and not 1 <= budget <= HARD_CAP:
        print(f"budget must be between 1 and {HARD_CAP}", file=sys.stderr)
        return 2
    _, real = key_for_cwd(os.getcwd())
    state: dict[str, Any] = {
        "objective": objective,
        "status": "active",
        "cwd": real,
        "budget_turns": budget,
        "continuations": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    reset_blocker_audit(state)
    save(state)
    print(json.dumps(state, indent=2))
    return 0


def require_state() -> dict[str, Any] | None:
    state = load()
    if not state:
        print("no goal set", file=sys.stderr)
    return state


def cmd_edit(args: argparse.Namespace) -> int:
    state = require_state()
    if not state:
        return 1
    objective = args.objective.strip()
    if not objective:
        print("objective must not be empty", file=sys.stderr)
        return 2
    state["objective"] = objective
    state["status"] = "active"
    reset_blocker_audit(state)
    save(state)
    print(json.dumps(state, indent=2))
    return 0


def set_status(value: str) -> int:
    state = require_state()
    if not state:
        return 1
    if value not in STATUSES:
        print(f"invalid status: {value}", file=sys.stderr)
        return 2
    state["status"] = value
    if value == "active":
        reset_blocker_audit(state)
    save(state)
    print(json.dumps(state, indent=2))
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    state = require_state()
    if not state:
        return 1
    reason = args.reason.strip()
    if not reason:
        print("block requires a stable --reason for the three-turn audit", file=sys.stderr)
        return 2
    continuation = int(state.get("continuations") or 0)
    prior_reason = state.get("blocker_signature")
    prior_turn = state.get("blocker_last_continuation")
    consecutive = prior_reason == reason and prior_turn == continuation - 1
    state["blocker_signature"] = reason
    state["blocker_turns"] = int(state.get("blocker_turns") or 0) + 1 if consecutive else 1
    state["blocker_last_continuation"] = continuation
    if state["blocker_turns"] >= 3:
        state["status"] = "blocked"
        save(state)
        print(json.dumps(state, indent=2))
        return 0
    save(state)
    print(
        f"blocker audit {state['blocker_turns']}/3; goal remains active",
        file=sys.stderr,
    )
    return 3


def cmd_get(_args: argparse.Namespace) -> int:
    print(json.dumps(load() or {}, indent=2))
    return 0


def cmd_clear(_args: argparse.Namespace) -> int:
    try:
        state_path().unlink()
        print("goal cleared")
    except FileNotFoundError:
        print("no goal to clear")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="goalctl")
    sub = parser.add_subparsers(dest="command", required=True)

    set_parser = sub.add_parser("set")
    set_parser.add_argument("objective")
    set_parser.add_argument("--budget", type=int)
    set_parser.set_defaults(func=cmd_set)

    edit_parser = sub.add_parser("edit")
    edit_parser.add_argument("objective")
    edit_parser.set_defaults(func=cmd_edit)

    sub.add_parser("get").set_defaults(func=cmd_get)
    sub.add_parser("clear").set_defaults(func=cmd_clear)

    status_parser = sub.add_parser("status")
    status_parser.add_argument("value", choices=STATUSES)
    status_parser.set_defaults(func=lambda args: set_status(args.value))

    for command, status in (
        ("pause", "paused"),
        ("resume", "active"),
        ("complete", "complete"),
    ):
        sub.add_parser(command).set_defaults(func=lambda _args, value=status: set_status(value))

    block_parser = sub.add_parser("block")
    block_parser.add_argument("--reason", required=True)
    block_parser.set_defaults(func=cmd_block)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
