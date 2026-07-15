#!/usr/bin/env python3
"""Cross-process lease for serializing repository-maintenance loops."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid
from typing import Iterator

LOCK_FILE = ".repo-maintenance.lock.json"
GUARD_FILE = ".repo-maintenance.guard"
DEFAULT_TTL_SECONDS = 7200
EXIT_BUSY = 3
EXIT_NOT_OWNER = 4


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


@contextmanager
def operation_guard(state_dir: Path) -> Iterator[None]:
    state_dir.mkdir(parents=True, exist_ok=True)
    guard_path = state_dir / GUARD_FILE
    with guard_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_state(path: Path, state: dict[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".pending",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def heartbeat_epoch(state: dict[str, object]) -> float:
    value = state.get("heartbeat_at_epoch")
    if not isinstance(value, (int, float)):
        raise ValueError("maintenance lock is missing heartbeat_at_epoch")
    return float(value)


def owner_ttl_seconds(state: dict[str, object]) -> int | float:
    """Read the owner's lifetime; legacy locks use the conservative default."""
    value = state.get("ttl_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_TTL_SECONDS
    normalized = float(value)
    return value if math.isfinite(normalized) and normalized >= 1 else DEFAULT_TTL_SECONDS


def expiration_epoch(state: dict[str, object]) -> float:
    value = state.get("expires_at_epoch")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return heartbeat_epoch(state) + owner_ttl_seconds(state)
    normalized = float(value)
    if not math.isfinite(normalized):
        return heartbeat_epoch(state) + owner_ttl_seconds(state)
    return normalized


def age_seconds(state: dict[str, object], now: float) -> float:
    return max(0.0, now - heartbeat_epoch(state))


def acquire(state_dir: Path, loop: str, ttl_seconds: int) -> int:
    lock_path = state_dir / LOCK_FILE
    with operation_guard(state_dir):
        now = time.time()
        existing = read_state(lock_path)
        if existing is not None:
            age = age_seconds(existing, now)
            if now <= expiration_epoch(existing):
                emit(
                    {
                        "status": "busy",
                        "loop": existing.get("loop", "unknown"),
                        "age_seconds": round(age, 3),
                    }
                )
                return EXIT_BUSY

        token = uuid.uuid4().hex
        state: dict[str, object] = {
            "token": token,
            "loop": loop,
            "pid": os.getpid(),
            "cwd": os.path.realpath(os.getcwd()),
            "acquired_at_epoch": now,
            "heartbeat_at_epoch": now,
            "ttl_seconds": ttl_seconds,
            "expires_at_epoch": now + ttl_seconds,
        }
        if existing is not None:
            state["replaced_stale_loop"] = existing.get("loop", "unknown")
        write_state(lock_path, state)
        emit({"status": "acquired", "loop": loop, "token": token})
        return 0


def heartbeat(state_dir: Path, token: str) -> int:
    lock_path = state_dir / LOCK_FILE
    with operation_guard(state_dir):
        state = read_state(lock_path)
        if state is None or state.get("token") != token:
            emit({"status": "not-owner"})
            return EXIT_NOT_OWNER
        ttl_seconds = owner_ttl_seconds(state)
        now = time.time()
        state["heartbeat_at_epoch"] = now
        state["ttl_seconds"] = ttl_seconds
        state["expires_at_epoch"] = now + ttl_seconds
        write_state(lock_path, state)
        emit({"status": "renewed", "loop": state.get("loop", "unknown")})
        return 0


def release(state_dir: Path, token: str) -> int:
    lock_path = state_dir / LOCK_FILE
    with operation_guard(state_dir):
        state = read_state(lock_path)
        if state is None or state.get("token") != token:
            emit({"status": "not-owner"})
            return EXIT_NOT_OWNER
        loop = state.get("loop", "unknown")
        lock_path.unlink()
        emit({"status": "released", "loop": loop})
        return 0


def status(state_dir: Path, ttl_seconds: int) -> int:
    lock_path = state_dir / LOCK_FILE
    with operation_guard(state_dir):
        state = read_state(lock_path)
        if state is None:
            emit({"status": "unlocked"})
            return 0
        now = time.time()
        age = age_seconds(state, now)
        emit(
            {
                "status": "stale" if now > expiration_epoch(state) else "locked",
                "loop": state.get("loop", "unknown"),
                "age_seconds": round(age, 3),
            }
        )
        return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)

    acquire_parser = commands.add_parser("acquire")
    acquire_parser.add_argument("state_dir", type=Path)
    acquire_parser.add_argument("--loop", required=True)
    acquire_parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)

    heartbeat_parser = commands.add_parser("heartbeat")
    heartbeat_parser.add_argument("state_dir", type=Path)
    heartbeat_parser.add_argument("--token", required=True)

    release_parser = commands.add_parser("release")
    release_parser.add_argument("state_dir", type=Path)
    release_parser.add_argument("--token", required=True)

    status_parser = commands.add_parser("status")
    status_parser.add_argument("state_dir", type=Path)
    status_parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    return value


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "ttl_seconds", 1) < 1:
        raise SystemExit("--ttl-seconds must be positive")
    if args.command == "acquire":
        return acquire(args.state_dir, args.loop, args.ttl_seconds)
    if args.command == "heartbeat":
        return heartbeat(args.state_dir, args.token)
    if args.command == "release":
        return release(args.state_dir, args.token)
    return status(args.state_dir, args.ttl_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
