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
        os.environ["GOAL_STATE_DIR"] = str(STATE)
        self.cwd = os.getcwd()

    def tearDown(self) -> None:
        os.chdir(self.cwd)
        if self.old_state is None:
            os.environ.pop("GOAL_STATE_DIR", None)
        else:
            os.environ["GOAL_STATE_DIR"] = self.old_state
        shutil.rmtree(STATE, ignore_errors=True)

    def call(self, *args: str) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return goalctl.main(list(args))

    def run_hook(self, payload: str = "{}") -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "GOAL_STATE_DIR": str(STATE),
            "GOALCTL_PATH": str(RUNTIME / "goalctl.py"),
        }
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
        self.assertEqual(self.call("set", "bounded work", "--budget", "1"), 0)
        first = self.run_hook(json.dumps({"cwd": os.getcwd()}))
        self.assertEqual(first.returncode, 0)
        self.assertEqual(json.loads(first.stdout)["decision"], "block")
        self.assertEqual(goalctl.load()["continuations"], 1)

        wrap = self.run_hook(json.dumps({"cwd": os.getcwd()}))
        self.assertEqual(json.loads(wrap.stdout)["decision"], "block")
        self.assertEqual(goalctl.load()["status"], "budget_limited")

        stopped = self.run_hook(json.dumps({"cwd": os.getcwd()}))
        self.assertEqual(stopped.stdout, "")

    def test_hook_is_fail_open_for_malformed_input(self) -> None:
        self.assertEqual(self.run_hook("{not-json").returncode, 0)
        self.assertEqual(self.run_hook("{not-json").stdout, "")

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


if __name__ == "__main__":
    unittest.main()
