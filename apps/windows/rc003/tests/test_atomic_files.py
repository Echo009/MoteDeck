from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from motedeck import atomic_files


class AtomicFilesTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_write_text_atomic_round_trip(self):
        target = self.root / "config.json"

        atomic_files.write_text_atomic(target, '{"a": 1}\n')

        self.assertEqual(target.read_text(encoding="utf-8"), '{"a": 1}\n')
        self.assertEqual(
            [path.name for path in self.root.iterdir()],
            ["config.json"],
        )

    def test_write_bytes_atomic_uses_resolved_directory(self):
        redirected = self.root / "redirected"
        real = self.root / "real"
        real.mkdir()

        with mock.patch.object(
            atomic_files, "resolve_real_path", return_value=real / "config.json"
        ):
            atomic_files.write_bytes_atomic(redirected / "config.json", b"payload")

        self.assertEqual((real / "config.json").read_bytes(), b"payload")
        self.assertFalse(redirected.exists())

    def test_replace_existing_falls_back_when_cross_device(self):
        target = self.root / "key_bindings.json"
        target.write_text("old", encoding="utf-8")
        temporary = self.root / ".pending.tmp"
        temporary.write_text("new", encoding="utf-8")
        not_same_device = OSError(17, "not same device")
        not_same_device.winerror = 17

        with mock.patch.object(
            atomic_files.os, "replace", side_effect=not_same_device
        ):
            atomic_files.replace_existing(temporary, target)

        self.assertEqual(target.read_text(encoding="utf-8"), "new")
        self.assertFalse(temporary.exists())
        self.assertEqual(
            [path.name for path in self.root.iterdir()],
            ["key_bindings.json"],
        )

    def test_replace_existing_raises_other_errors(self):
        target = self.root / "config.json"
        temporary = self.root / ".pending.tmp"
        temporary.write_text("new", encoding="utf-8")

        with mock.patch.object(
            atomic_files.os, "replace", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(PermissionError):
                atomic_files.replace_existing(temporary, target)

        self.assertTrue(temporary.exists())

    def test_prepare_called_after_fallback_overwrite(self):
        target = self.root / "manifest.json"
        target.write_text("old", encoding="utf-8")
        temporary = self.root / ".pending.tmp"
        temporary.write_text("new", encoding="utf-8")
        prepared = []
        not_same_device = OSError(17, "not same device")
        not_same_device.winerror = 17

        with mock.patch.object(
            atomic_files.os, "replace", side_effect=not_same_device
        ):
            atomic_files.replace_existing(
                temporary, target, prepare=lambda path: prepared.append(path)
            )

        self.assertEqual(prepared, [target])

    def test_resolve_real_path_keeps_missing_file_name(self):
        missing = self.root / "not-created" / "config.json"

        resolved = atomic_files.resolve_real_path(missing)

        self.assertEqual(resolved.name, "config.json")
        self.assertEqual(resolved.exists(), False)


if __name__ == "__main__":
    unittest.main()
