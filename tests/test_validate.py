"""Regression tests for the packaging validator itself.

These lock in the two invariants that keep `tests/validate.py` deterministic
and evidence-driven:

1. `validate_maintenance` must ignore any file that is not part of the
   authoritative `MAINTENANCE_RESOURCES` inventory. A stray binary or
   compiled artifact under the packaged directory (e.g. `__pycache__/*.pyc`
   left by the interpreter) must not make the scan raise UnicodeDecodeError
   and must not silently skip the safety assertions.

2. The forbidden-text check must actually cover every declared maintenance
   resource, so the check can never be trivially bypassed by shrinking the
   scanned set.
"""

from __future__ import annotations

import importlib.util
import shutil
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = ROOT / "tests/validate.py"


def _load_validate_module():
    spec = importlib.util.spec_from_file_location("plugin_validate", VALIDATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidateMaintenanceScanTests(unittest.TestCase):
    """`validate_maintenance` must be robust to non-inventory files."""

    def setUp(self) -> None:
        self.module = _load_validate_module()
        self.stray_dir = ROOT / "skills/repo-maintenance/runtime/__pycache__"
        self.stray_file = self.stray_dir / "planted-binary.cpython-999.pyc"
        # Non-utf8 payload — exactly the shape of a real Python bytecode file
        # that would raise UnicodeDecodeError under `read_text(encoding="utf-8")`.
        self.stray_dir.mkdir(parents=True, exist_ok=True)
        self.stray_file.write_bytes(b"\xe3\x00\x00\x00\xff\xfe\xfd binary payload \x00")

    def tearDown(self) -> None:
        try:
            self.stray_file.unlink()
        except FileNotFoundError:
            pass
        if self.stray_dir.exists() and not any(self.stray_dir.iterdir()):
            self.stray_dir.rmdir()

    def test_maintenance_scan_ignores_undeclared_binary_files(self) -> None:
        # The scan must run to completion (no UnicodeDecodeError from the
        # planted binary) AND all safety assertions must execute.
        self.module.validate_maintenance()

    def test_forbidden_text_scan_covers_every_declared_resource(self) -> None:
        # Structural guarantee: the forbidden-text scan must include every
        # entry in the authoritative inventory. Any implementation that only
        # scans a subset would let non-portable strings sneak into an
        # unscanned resource.
        source = VALIDATE_PATH.read_text(encoding="utf-8")
        self.assertIn("sorted(MAINTENANCE_RESOURCES)", source)
        self.assertNotIn(
            'shared.rglob("*")',
            source,
            "validate_maintenance must not fall back to a loose filesystem walk",
        )

    def test_planted_forbidden_binary_does_not_shadow_safety_checks(self) -> None:
        # Even if a compiled `.pyc` contained bytes that spell one of the
        # forbidden strings (e.g. "notify-costas"), the utf-8-decoded view
        # of the inventory must remain the only source scanned. We prove
        # this by planting such a file and confirming validation still
        # succeeds — i.e. the forbidden check never reads the binary.
        planted = self.stray_dir / "sentinel.cpython-999.pyc"
        planted.write_bytes(b"\x00notify-costas\x00~/.claude/\x00/Users/\x00")
        try:
            self.module.validate_maintenance()
        finally:
            planted.unlink()


if __name__ == "__main__":
    unittest.main()
