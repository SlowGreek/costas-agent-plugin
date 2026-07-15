from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
STATE = ROOT / "tests" / ".goal-test-state"

sys.path.insert(0, str(RUNTIME))
import goalctl  # noqa: E402


class GoalTests(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(STATE, ignore_errors=True)
        STATE.mkdir(parents=True)
        self.old_state = os.environ.get("GOAL_STATE_DIR")
        self.old_session_id = os.environ.pop("COPILOT_AGENT_SESSION_ID", None)
        os.environ["GOAL_STATE_DIR"] = str(STATE)
        self.cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        if self.old_state is None:
            os.environ.pop("GOAL_STATE_DIR", None)
        else:
            os.environ["GOAL_STATE_DIR"] = self.old_state
        if self.old_session_id is None:
            os.environ.pop("COPILOT_AGENT_SESSION_ID", None)
        else:
            os.environ["COPILOT_AGENT_SESSION_ID"] = self.old_session_id
        shutil.rmtree(STATE, ignore_errors=True)

    def call(self, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return goalctl.main(list(args))

    def run_hook(
        self,
        payload: str = "{}",
        hook_session_id: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "GOAL_STATE_DIR": str(STATE),
            "GOALCTL_PATH": str(RUNTIME / "goalctl.py"),
        }
        env.pop("COPILOT_AGENT_SESSION_ID", None)
        if hook_session_id is not None:
            env["COPILOT_AGENT_SESSION_ID"] = hook_session_id
        return subprocess.run(
            [sys.executable, str(RUNTIME / "goal_continue.py")],
            input=payload,
            text=True,
            capture_output=True,
            cwd=ROOT,
            env=env,
            check=False,
        )

    def test_state_transitions(self) -> None:
        self.assertEqual(self.call("set", "finish the plugin", "--budget", "4"), 0)
        self.assertEqual(goalctl.load()["status"], "active")
        self.assertEqual(self.call("pause"), 0)
        self.assertEqual(goalctl.load()["status"], "paused")
        self.assertEqual(self.call("resume"), 0)
        self.assertEqual(goalctl.load()["status"], "active")
        self.assertEqual(self.call("complete"), 0)
        self.assertEqual(goalctl.load()["status"], "complete")

    def test_default_continuation_and_budget_wrap_up(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "bounded work", "--budget", "1"), 0)
        payload = json.dumps({"cwd": os.getcwd(), "sessionId": "root-session"})
        first = self.run_hook(payload)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        self.assertEqual(goalctl.load()["continuations"], 1)

        wrap = self.run_hook(payload)
        self.assertEqual(json.loads(wrap.stdout)["decision"], "block")
        self.assertEqual(goalctl.load()["status"], "budget_limited")

        stopped = self.run_hook(payload)
        self.assertEqual(stopped.stdout, "")

    def test_hook_is_fail_open_for_malformed_or_missing_identity(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "protected objective", "--budget", "2"), 0)

        payloads = (
            "{not-json",
            json.dumps({"cwd": os.getcwd()}),
            json.dumps({"cwd": os.getcwd(), "sessionId": None}),
            json.dumps({"cwd": os.getcwd(), "sessionId": "  "}),
            json.dumps({"cwd": os.getcwd(), "sessionId": 42}),
            json.dumps([]),
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                stopped = self.run_hook(payload, hook_session_id="root-session")
                self.assertEqual(stopped.returncode, 0)
                self.assertEqual(stopped.stdout, "")

        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 0)

    def test_hook_is_fail_open_for_malformed_or_missing_cwd(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "protected objective", "--budget", "2"), 0)

        payloads = (
            {"sessionId": "root-session"},
            {"cwd": None, "sessionId": "root-session"},
            {"cwd": "  ", "sessionId": "root-session"},
            {"cwd": 42, "sessionId": "root-session"},
            {"cwd": [os.getcwd()], "sessionId": "root-session"},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                stopped = self.run_hook(json.dumps(payload))
                self.assertEqual(stopped.returncode, 0)
                self.assertEqual(stopped.stdout, "")

        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 0)

    def test_block_requires_three_consecutive_goal_turns(self) -> None:
        self.assertEqual(self.call("set", "work until truly blocked", "--budget", "10"), 0)
        for expected in (1, 2):
            state = goalctl.load()
            state["continuations"] = expected
            goalctl.save(state)
            self.assertEqual(self.call("block", "--reason", "same external dependency"), 3)
            self.assertEqual(goalctl.load()["status"], "active")
            self.assertEqual(goalctl.load()["blocker_turns"], expected)

        state = goalctl.load()
        state["continuations"] = 3
        goalctl.save(state)
        self.assertEqual(self.call("block", "--reason", "same external dependency"), 0)
        self.assertEqual(goalctl.load()["status"], "blocked")

    def test_changed_or_nonconsecutive_blocker_restarts_audit(self) -> None:
        self.assertEqual(self.call("set", "audit blockers", "--budget", "10"), 0)
        state = goalctl.load()
        state["continuations"] = 1
        goalctl.save(state)
        self.assertEqual(self.call("block", "--reason", "one"), 3)
        state = goalctl.load()
        state["continuations"] = 3
        goalctl.save(state)
        self.assertEqual(self.call("block", "--reason", "one"), 3)
        self.assertEqual(goalctl.load()["blocker_turns"], 1)
        state = goalctl.load()
        state["continuations"] = 4
        goalctl.save(state)
        self.assertEqual(self.call("block", "--reason", "two"), 3)
        self.assertEqual(goalctl.load()["blocker_turns"], 1)

    def test_hard_cap_rejects_oversized_budget(self) -> None:
        self.assertEqual(self.call("set", "unsafe", "--budget", "101"), 2)
        self.assertIsNone(goalctl.load())

    def test_root_hook_payload_consumes_tool_created_goal_without_hook_env(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "root objective", "--budget", "2"), 0)
        state = goalctl.load(session_id="root-session")
        self.assertEqual(state["session_id"], "root-session")
        os.environ.pop("COPILOT_AGENT_SESSION_ID", None)

        stopped = self.run_hook(
            json.dumps({"cwd": os.getcwd(), "sessionId": "  root-session  "})
        )

        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(json.loads(stopped.stdout)["decision"], "block")
        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 1)
        self.assertIsNone(goalctl.load(session_id=None))

    def test_child_hook_payload_does_not_consume_root_goal_with_root_ambient_env(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "root objective", "--budget", "2"), 0)

        stopped = self.run_hook(
            json.dumps({"cwd": os.getcwd(), "sessionId": "child-agent-id"}),
            hook_session_id="root-session",
        )

        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stopped.stdout, "")
        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 0)
        self.assertIsNone(goalctl.load(session_id="child-agent-id"))

    def test_other_root_payload_does_not_consume_root_goal(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "root objective", "--budget", "2"), 0)

        stopped = self.run_hook(
            json.dumps({"cwd": os.getcwd(), "sessionId": "other-root-session"}),
            hook_session_id="root-session",
        )

        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stopped.stdout, "")
        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 0)
        self.assertIsNone(goalctl.load(session_id="other-root-session"))

    def test_hook_helper_uses_normalized_payload_only(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "goal_continue_check", RUNTIME / "goal_continue.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(
            module.hook_session_id({"sessionId": "  child-agent-id  "}),
            "child-agent-id",
        )
        self.assertEqual(module.hook_cwd({"cwd": f"  {self.cwd}  "}), self.cwd)
        for payload in (
            {},
            {"sessionId": None},
            {"sessionId": ""},
            {"sessionId": 42},
            {"sessionId": ["root-session"]},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(module.hook_session_id(payload))
        for payload in (
            {},
            {"cwd": None},
            {"cwd": ""},
            {"cwd": 42},
            {"cwd": [self.cwd]},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(module.hook_cwd(payload))

    def test_state_path_matches_plugin_data_for_installed_and_direct_plugins(self) -> None:
        original_file = goalctl.__file__
        original_home = os.environ.get("COPILOT_HOME")
        original_state = os.environ.pop("GOAL_STATE_DIR", None)
        original_plugin_data = os.environ.pop("COPILOT_PLUGIN_DATA", None)
        volume_root = Path(Path.cwd().anchor or os.sep)
        try:
            installed_goalctl = (
                volume_root
                / "copilot-home"
                / "installed-plugins"
                / "example-market"
                / "costas-agent-plugin"
                / "runtime"
                / "goalctl.py"
            )
            goalctl.__file__ = str(installed_goalctl)
            self.assertEqual(
                goalctl.goals_dir(),
                volume_root
                / "copilot-home"
                / "plugin-data"
                / "example-market"
                / "costas-agent-plugin"
                / "goals",
            )
            goalctl.__file__ = str(
                volume_root / "source" / "costas-agent-plugin" / "runtime" / "goalctl.py"
            )
            os.environ["COPILOT_HOME"] = str(volume_root / "isolated" / "copilot-home")
            self.assertEqual(
                goalctl.goals_dir(),
                volume_root
                / "isolated"
                / "copilot-home"
                / "plugin-data"
                / "_direct"
                / "costas-agent-plugin"
                / "goals",
            )
        finally:
            goalctl.__file__ = original_file
            if original_home is None:
                os.environ.pop("COPILOT_HOME", None)
            else:
                os.environ["COPILOT_HOME"] = original_home
            if original_state is not None:
                os.environ["GOAL_STATE_DIR"] = original_state
            if original_plugin_data is not None:
                os.environ["COPILOT_PLUGIN_DATA"] = original_plugin_data

    def _write_legacy_goal(self, **fields: Any) -> Path:
        goalctl.goals_dir().mkdir(parents=True, exist_ok=True)
        path = goalctl.legacy_state_path(self.cwd)
        state: dict[str, Any] = {
            "objective": "legacy objective",
            "status": "active",
            "cwd": self.cwd,
            "budget_turns": 5,
            "continuations": 2,
            "created_at": goalctl.now_iso(),
            "updated_at": goalctl.now_iso(),
            "blocker_signature": None,
            "blocker_turns": 0,
            "blocker_last_continuation": None,
        }
        state.update(fields)
        path.write_text(f"{json.dumps(state, indent=2)}\n", encoding="utf-8")
        return path

    def test_active_legacy_state_is_claimed_once_by_a_session(self) -> None:
        self._write_legacy_goal(status="active", objective="ship v1.0 goal")
        loaded = goalctl.load(session_id="session-one")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["objective"], "ship v1.0 goal")
        self.assertEqual(loaded["status"], "active")
        self.assertEqual(loaded["continuations"], 2)
        self.assertEqual(loaded["session_id"], "session-one")
        self.assertTrue(loaded.get("migrated_from_legacy"))
        # The legacy file was consumed (moved, not copied) into the scoped slot.
        self.assertFalse(goalctl.legacy_state_path(self.cwd).exists())
        self.assertTrue(goalctl.state_path(session_id="session-one").exists())

    def test_set_consumes_legacy_state_before_replacing_it(self) -> None:
        self._write_legacy_goal(status="active", objective="stale v1.0 goal")
        os.environ["COPILOT_AGENT_SESSION_ID"] = "session-one"

        self.assertEqual(self.call("set", "fresh scoped goal", "--budget", "3"), 0)

        session_one = goalctl.load(session_id="session-one")
        self.assertEqual(session_one["objective"], "fresh scoped goal")
        self.assertEqual(session_one["session_id"], "session-one")
        self.assertFalse(goalctl.legacy_state_path(self.cwd).exists())
        self.assertIsNone(goalctl.load(session_id="session-two"))
        self.assertFalse(goalctl.state_path(session_id="session-two").exists())

    def test_stale_legacy_claim_recovers_to_original_session(self) -> None:
        legacy = self._write_legacy_goal(status="active", objective="orphaned claim goal")
        scoped = goalctl.state_path(session_id="session-one")
        claim = scoped.with_name(f"{scoped.name}.999.claim")
        os.rename(legacy, claim)
        stale_time = time.time() - goalctl.CLAIM_STALE_SECONDS - 1
        os.utime(claim, (stale_time, stale_time))

        recovered = goalctl.load(session_id="session-one")

        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["objective"], "orphaned claim goal")
        self.assertEqual(recovered["session_id"], "session-one")
        self.assertTrue(recovered.get("migrated_from_legacy"))
        self.assertTrue(scoped.exists())
        self.assertFalse(claim.exists())
        self.assertFalse(goalctl.legacy_state_path(self.cwd).exists())
        self.assertIsNone(goalctl.load(session_id="session-two"))

    def test_paused_legacy_state_migrates_without_changing_status(self) -> None:
        self._write_legacy_goal(status="paused", objective="paused legacy work")
        loaded = goalctl.load(session_id="session-one")
        self.assertEqual(loaded["status"], "paused")
        self.assertEqual(loaded["session_id"], "session-one")
        self.assertFalse(goalctl.legacy_state_path(self.cwd).exists())

    def test_existing_scoped_state_is_not_overwritten_by_legacy(self) -> None:
        os.environ["COPILOT_AGENT_SESSION_ID"] = "session-one"
        self.assertEqual(self.call("set", "scoped objective", "--budget", "3"), 0)
        os.environ.pop("COPILOT_AGENT_SESSION_ID", None)
        legacy_path = self._write_legacy_goal(objective="legacy objective")

        loaded = goalctl.load(session_id="session-one")
        self.assertEqual(loaded["objective"], "scoped objective")
        self.assertNotIn("migrated_from_legacy", loaded)
        # The legacy file is left completely untouched.
        self.assertTrue(legacy_path.exists())
        legacy_state = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(legacy_state["objective"], "legacy objective")

    # --- Regression: the automated agentStop hook must never migrate legacy
    # state, because it cannot prove the payload's session id is the goal's
    # rightful root owner (see runtime/goalctl.py load_without_legacy_claim).

    def test_child_stop_hook_never_claims_legacy_state(self) -> None:
        legacy_path = self._write_legacy_goal(status="active", objective="pre-upgrade root goal")

        # A dispatched child's agentStop fires first, identified only by the
        # stop payload's sessionId (per goal/SKILL.md, its tool shell inherits
        # the root's ambient env, so ambient env must not matter here either).
        stopped = self.run_hook(
            json.dumps({"cwd": self.cwd, "sessionId": "child-agent-id"}),
            hook_session_id="root-session",
        )

        # Fail-open: the hook must allow stop with no output, not block the
        # child on a goal it never provably owns.
        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stopped.stdout, "")
        # The legacy goal is retained exactly as written — untouched, not
        # claimed, not moved into a claim file, not stamped with the child's
        # session id.
        self.assertTrue(legacy_path.exists())
        legacy_state = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(legacy_state["objective"], "pre-upgrade root goal")
        self.assertNotIn("session_id", legacy_state)
        self.assertEqual(goalctl.legacy_claim_paths(goalctl.state_path(session_id="child-agent-id")), [])
        self.assertIsNone(goalctl.load_without_legacy_claim(session_id="child-agent-id"))
        self.assertFalse(goalctl.state_path(session_id="child-agent-id").exists())

        # Root can still subsequently claim it explicitly (e.g. a later
        # `goalctl status`/`get`/`set` in the real root session).
        claimed = goalctl.load(session_id="root-session")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["objective"], "pre-upgrade root goal")
        self.assertEqual(claimed["session_id"], "root-session")
        self.assertTrue(claimed.get("migrated_from_legacy"))
        self.assertFalse(legacy_path.exists())

    def test_root_stop_hook_also_never_claims_legacy_state(self) -> None:
        # Even when the payload's session id IS what will become the real root
        # session, the hook cannot prove that at the time it fires (identity
        # is unproven from a payload alone), so it must not claim either.
        legacy_path = self._write_legacy_goal(status="active", objective="unclaimed root goal")

        stopped = self.run_hook(
            json.dumps({"cwd": self.cwd, "sessionId": "root-session"}),
            hook_session_id="root-session",
        )

        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(stopped.stdout, "")
        self.assertTrue(legacy_path.exists())
        self.assertFalse(goalctl.state_path(session_id="root-session").exists())

        # The legacy goal remains fully drainable by an explicit later claim.
        claimed = goalctl.load(session_id="root-session")
        self.assertEqual(claimed["objective"], "unclaimed root goal")
        self.assertEqual(claimed["session_id"], "root-session")
        self.assertFalse(legacy_path.exists())

    def test_hook_still_drives_an_existing_scoped_goal_when_legacy_also_exists(self) -> None:
        # Regression for existing (already-migrated or native v1.1) scoped
        # behavior: the hook must keep working normally for a session that
        # already owns its own scoped goal, even if an unrelated legacy file
        # happens to sit at the same cwd (e.g. another pre-upgrade artifact).
        os.environ["COPILOT_AGENT_SESSION_ID"] = "root-session"
        self.assertEqual(self.call("set", "native scoped objective", "--budget", "5"), 0)
        os.environ.pop("COPILOT_AGENT_SESSION_ID", None)
        legacy_path = self._write_legacy_goal(objective="unrelated legacy goal")

        payload = json.dumps({"cwd": self.cwd, "sessionId": "root-session"})
        stopped = self.run_hook(payload)

        self.assertEqual(stopped.returncode, 0)
        self.assertEqual(json.loads(stopped.stdout)["decision"], "block")
        self.assertEqual(goalctl.load(session_id="root-session")["continuations"], 1)
        # The unrelated legacy file is never touched by driving the scoped goal.
        self.assertTrue(legacy_path.exists())
        legacy_state = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(legacy_state["objective"], "unrelated legacy goal")

    def test_legacy_claim_is_single_winner_across_sessions(self) -> None:
        self._write_legacy_goal(objective="contended legacy goal")

        winner = goalctl.load(session_id="session-one")
        self.assertEqual(winner["objective"], "contended legacy goal")
        self.assertEqual(winner["session_id"], "session-one")

        # A second session sees no scoped file and the legacy file already
        # consumed, so it can neither adopt nor copy the goal.
        loser = goalctl.load(session_id="session-two")
        self.assertIsNone(loser)
        self.assertTrue(goalctl.state_path(session_id="session-one").exists())
        self.assertFalse(goalctl.state_path(session_id="session-two").exists())
        self.assertFalse(goalctl.legacy_state_path(self.cwd).exists())

    def test_no_session_operation_remains_legacy_compatible(self) -> None:
        os.environ.pop("COPILOT_AGENT_SESSION_ID", None)
        legacy_path = self._write_legacy_goal(objective="no-session legacy goal")

        loaded = goalctl.load()
        self.assertEqual(loaded["objective"], "no-session legacy goal")
        self.assertNotIn("session_id", loaded)
        # No migration happens without a session: the file is read in place.
        self.assertTrue(legacy_path.exists())
        self.assertEqual(goalctl.state_path(), legacy_path)


if __name__ == "__main__":
    unittest.main()
