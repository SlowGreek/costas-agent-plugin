#!/usr/bin/env python3
"""Portable per-session and per-worktree state controller for /goal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Any

STATUSES = ("active", "paused", "blocked", "budget_limited", "complete")
DEFAULT_BUDGET_TURNS = 30
HARD_CAP = 100
PLUGIN_NAME = "costas-agent-plugin"
CLAIM_STALE_SECONDS = 300


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


def effective_session_id(explicit: str | None = None) -> str | None:
    value = explicit if explicit is not None else os.environ.get("COPILOT_AGENT_SESSION_ID")
    normalized = str(value or "").strip()
    return normalized or None


def key_for_cwd(
    cwd: str | os.PathLike[str],
    session_id: str | None = None,
) -> tuple[str, str]:
    real = os.path.realpath(os.fspath(cwd))
    scoped_session = effective_session_id(session_id)
    identity = real if scoped_session is None else f"{real}\0session:{scoped_session}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16], real


def legacy_state_path(cwd: str | os.PathLike[str]) -> Path:
    """The v1.0 cwd-only state path, independent of any ambient session id.

    v1.0 keyed goal state purely on the real cwd. v1.1 adds a session segment,
    so a pre-upgrade goal becomes invisible to a session-scoped load. This
    resolves that legacy path explicitly (never reading the environment) so it
    can be migrated exactly once.
    """
    real = os.path.realpath(os.fspath(cwd))
    key = hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]
    return goals_dir() / f"{key}.json"


def state_path(
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> Path:
    key, _ = key_for_cwd(cwd or os.getcwd(), session_id)
    return goals_dir() / f"{key}.json"


def legacy_claim_paths(scoped: Path) -> list[Path]:
    return [
        claim
        for claim in sorted(scoped.parent.glob(f"{scoped.name}.*.claim"))
        if not claim.name.endswith(".discard.claim")
    ]


def claim_path_for(scoped: Path, index: int = 0, recoverable: bool = True) -> Path:
    suffix = str(os.getpid()) if index == 0 else f"{os.getpid()}-{index}"
    kind = "claim" if recoverable else "discard.claim"
    return scoped.with_name(f"{scoped.name}.{suffix}.{kind}")


def claim_is_stale(claim: Path, stale_after: int = CLAIM_STALE_SECONDS) -> bool:
    try:
        return time.time() - claim.stat().st_mtime >= stale_after
    except FileNotFoundError:
        return False


def install_text_without_overwrite(text: str, destination: Path) -> bool:
    staging = destination.with_name(f"{destination.name}.{os.getpid()}.pending")
    staging.write_text(text, encoding="utf-8")
    try:
        os.link(staging, destination)
    except FileExistsError:
        return False
    finally:
        staging.unlink(missing_ok=True)
    return True


def promote_claim_to_scoped(claim: Path, scoped: Path, sid: str) -> bool:
    raw = claim.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        text = raw
    else:
        if isinstance(data, dict):
            data["session_id"] = sid
            data["migrated_from_legacy"] = True
            text = f"{json.dumps(data, indent=2)}\n"
        else:
            text = raw
    installed = install_text_without_overwrite(text, scoped)
    if installed:
        claim.unlink(missing_ok=True)
    return installed


def recover_stale_claim(scoped: Path, sid: str) -> bool:
    if scoped.exists():
        return False
    for claim in legacy_claim_paths(scoped):
        try:
            if not claim_is_stale(claim):
                continue
            if promote_claim_to_scoped(claim, scoped, sid):
                return True
        except (FileNotFoundError, OSError):
            continue
    return False


def move_legacy_to_claim(legacy: Path, scoped: Path, recoverable: bool = True) -> Path | None:
    for index in range(1000):
        claim = claim_path_for(scoped, index, recoverable)
        if claim.exists():
            continue
        try:
            os.rename(legacy, claim)
        except FileNotFoundError:
            return None
        except FileExistsError:
            continue
        except OSError:
            return None
        return claim
    return None


def claim_legacy_state(
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> Path | None:
    """One-time, single-winner migration of a v1.0 cwd-only goal into the
    current session's scoped slot.

    A no-session operation stays legacy-compatible (it reads/writes the cwd-only
    path directly, so nothing is migrated). When a session is in effect and the
    scoped slot is empty but a legacy file exists, exactly one session claims it
    by atomically renaming the legacy file — a move, never a copy — so two
    racing sessions can never both adopt it, and an existing scoped file is
    never overwritten. The intermediate claim is session-targeted, discoverable,
    and recoverable if it becomes stale after a crash.
    """
    sid = effective_session_id(session_id)
    if sid is None:
        return None
    resolved_cwd = cwd or os.getcwd()
    scoped = state_path(resolved_cwd, sid)
    legacy = legacy_state_path(resolved_cwd)
    if scoped == legacy:
        return None
    if not scoped.exists():
        recover_stale_claim(scoped, sid)
    if scoped.exists() or not legacy.exists():
        return None

    # Atomic single-winner handoff: os.rename consumes the shared legacy file. A
    # second session racing on the same legacy file finds the source already gone
    # and no-ops, so it can never copy the goal a second time.
    claim = move_legacy_to_claim(legacy, scoped)
    if claim is None:
        return None
    try:
        if promote_claim_to_scoped(claim, scoped, sid):
            return None
    except OSError:
        return claim
    return claim


def consume_legacy_state(
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> Path | None:
    """Consume any v1.0 cwd-only slot before writing a replacement goal."""
    sid = effective_session_id(session_id)
    if sid is None:
        return None
    resolved_cwd = cwd or os.getcwd()
    scoped = state_path(resolved_cwd, sid)
    legacy = legacy_state_path(resolved_cwd)
    if scoped == legacy:
        return None
    claimed = claim_legacy_state(resolved_cwd, sid)
    if claimed is not None or not legacy.exists():
        return claimed
    return move_legacy_to_claim(legacy, scoped, recoverable=False)


def load(
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    claim_legacy_state(cwd, session_id)
    return load_without_legacy_claim(cwd, session_id)


def load_without_legacy_claim(
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Read only this session's own scoped slot; never migrates legacy state.

    An automated, non-explicit reader (the agentStop hook) receives whatever
    session id happens to be in its payload — it cannot prove that id is the
    rightful root owner of a pre-v1.1, cwd-only legacy goal. If it called
    `load()` it would silently single-winner-claim an unowned legacy file via
    `claim_legacy_state`, which can permanently hide that goal from its actual
    owner (e.g. a child agent's stop event racing ahead of root's). This
    variant never calls `claim_legacy_state`, so it is safe for any automated
    or unproven caller: when the scoped slot already exists (native v1.1 state,
    or a goal already migrated by an explicit root action) behavior is
    identical to `load`; when it does not, this returns None instead of
    adopting a legacy file, leaving it fully intact for an explicit CLI
    invocation (`set`/`get`/`status`/etc.) to claim later.
    """
    try:
        value = json.loads(state_path(cwd, session_id).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save(
    state: dict[str, Any],
    cwd: str | os.PathLike[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    directory = goals_dir()
    directory.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now_iso()
    destination = state_path(cwd, session_id)
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
    session_id = effective_session_id()
    cwd = os.getcwd()
    legacy_claim = consume_legacy_state(cwd, session_id)
    if session_id is not None and legacy_state_path(cwd).exists():
        print("could not claim legacy goal state", file=sys.stderr)
        return 1
    _, real = key_for_cwd(cwd, session_id)
    state: dict[str, Any] = {
        "objective": objective,
        "status": "active",
        "cwd": real,
        "budget_turns": budget,
        "continuations": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if session_id is not None:
        state["session_id"] = session_id
    reset_blocker_audit(state)
    save(state)
    if legacy_claim is not None:
        legacy_claim.unlink(missing_ok=True)
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
    claim_legacy_state()
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
