from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/repo-maintenance/runtime/maintenance_lock.py"


class MaintenanceLockTests(unittest.TestCase):
    def invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_lease_serializes_owners_and_recovers_stale_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)

            first = self.invoke("acquire", str(state_dir), "--loop", "triage")
            self.assertEqual(first.returncode, 0, first.stderr)
            first_token = json.loads(first.stdout)["token"]

            busy = self.invoke("acquire", str(state_dir), "--loop", "implement")
            self.assertEqual(busy.returncode, 3, busy.stderr)
            self.assertEqual(json.loads(busy.stdout)["status"], "busy")

            wrong_release = self.invoke("release", str(state_dir), "--token", "wrong")
            self.assertEqual(wrong_release.returncode, 4, wrong_release.stderr)

            renewed = self.invoke("heartbeat", str(state_dir), "--token", first_token)
            self.assertEqual(renewed.returncode, 0, renewed.stderr)

            released = self.invoke("release", str(state_dir), "--token", first_token)
            self.assertEqual(released.returncode, 0, released.stderr)

            second = self.invoke(
                "acquire",
                str(state_dir),
                "--loop",
                "implement",
                "--ttl-seconds",
                "1",
            )
            self.assertEqual(second.returncode, 0, second.stderr)

            lock_path = state_dir / ".repo-maintenance.lock.json"
            state = json.loads(lock_path.read_text(encoding="utf-8"))
            state["heartbeat_at_epoch"] = time.time() - 10
            state["expires_at_epoch"] = state["heartbeat_at_epoch"] + 1
            lock_path.write_text(f"{json.dumps(state)}\n", encoding="utf-8")

            replacement = self.invoke(
                "acquire",
                str(state_dir),
                "--loop",
                "post-merge",
                "--ttl-seconds",
                "1",
            )
            self.assertEqual(replacement.returncode, 0, replacement.stderr)
            replacement_payload = json.loads(replacement.stdout)
            self.assertEqual(replacement_payload["status"], "acquired")
            self.assertEqual(replacement_payload["loop"], "post-merge")

    def test_contender_cannot_shorten_owner_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            owner = self.invoke(
                "acquire",
                str(state_dir),
                "--loop",
                "long-owner",
                "--ttl-seconds",
                "3600",
            )
            self.assertEqual(owner.returncode, 0, owner.stderr)
            owner_token = json.loads(owner.stdout)["token"]

            lock_path = state_dir / ".repo-maintenance.lock.json"
            state = json.loads(lock_path.read_text(encoding="utf-8"))
            state["heartbeat_at_epoch"] = time.time() - 2
            state["expires_at_epoch"] = state["heartbeat_at_epoch"] + 3600
            lock_path.write_text(f"{json.dumps(state)}\n", encoding="utf-8")

            contender = self.invoke(
                "acquire",
                str(state_dir),
                "--loop",
                "short-contender",
                "--ttl-seconds",
                "1",
            )
            self.assertEqual(contender.returncode, 3, contender.stderr)
            self.assertEqual(json.loads(contender.stdout)["status"], "busy")
            self.assertEqual(
                json.loads(lock_path.read_text(encoding="utf-8"))["token"],
                owner_token,
            )

            renewed = self.invoke("heartbeat", str(state_dir), "--token", owner_token)
            self.assertEqual(renewed.returncode, 0, renewed.stderr)
            renewed_state = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(renewed_state["ttl_seconds"], 3600)
            self.assertGreater(
                renewed_state["expires_at_epoch"],
                renewed_state["heartbeat_at_epoch"] + 3599,
            )

    def test_legacy_lock_without_owner_ttl_uses_safe_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_dir = Path(temporary)
            owner = self.invoke("acquire", str(state_dir), "--loop", "legacy-owner")
            self.assertEqual(owner.returncode, 0, owner.stderr)
            token = json.loads(owner.stdout)["token"]

            lock_path = state_dir / ".repo-maintenance.lock.json"
            state = json.loads(lock_path.read_text(encoding="utf-8"))
            state.pop("ttl_seconds", None)
            state.pop("expires_at_epoch", None)
            state["heartbeat_at_epoch"] = time.time() - 2
            lock_path.write_text(f"{json.dumps(state)}\n", encoding="utf-8")

            contender = self.invoke(
                "acquire",
                str(state_dir),
                "--loop",
                "short-contender",
                "--ttl-seconds",
                "1",
            )
            self.assertEqual(contender.returncode, 3, contender.stderr)

            renewed = self.invoke("heartbeat", str(state_dir), "--token", token)
            self.assertEqual(renewed.returncode, 0, renewed.stderr)
            upgraded = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(upgraded["ttl_seconds"], 7200)


if __name__ == "__main__":
    unittest.main()
