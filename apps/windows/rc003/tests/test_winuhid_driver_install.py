"""Contract tests for the bundled WinUHid driver installer.

Everything here is a pure file-system/registry contract: no elevated process is
started and no real registry key is read or written.
"""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from ovb_rc003 import winuhid_driver_install as installer


def _write_package(directory: Path, *, skip=()) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in installer.REQUIRED_PACKAGE_FILES:
        if name in skip:
            continue
        (directory / name).write_bytes(b"fixture")


def _write_script(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / installer.SCRIPT_NAME
    path.write_text("# fixture install script\n", encoding="utf-8")
    return path


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_winreg(*, names=(), open_error=None):
    module = types.ModuleType("winreg")
    module.HKEY_LOCAL_MACHINE = 1

    def open_key(root, path):
        if open_error is not None:
            raise open_error
        return _FakeKey()

    def enum_key(key, index):
        if index < len(names):
            return names[index]
        raise OSError(259, "no more items")

    module.OpenKey = open_key
    module.EnumKey = enum_key
    return module


class DriverPackageDiscoveryTests(unittest.TestCase):
    def test_package_dir_follows_the_environment_override(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(
            os.environ, {"RC003_WINUHID_PACKAGE": temporary}
        ):
            expected = Path(temporary)
            _write_package(expected)
            self.assertEqual(Path(installer.package_dir()), expected)
            self.assertEqual(installer.missing_package_files(), ())

    def test_missing_package_files_reports_only_the_absent_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            skipped = installer.REQUIRED_PACKAGE_FILES[1:]
            _write_package(directory, skip=skipped)
            with mock.patch.dict(
                os.environ, {"RC003_WINUHID_PACKAGE": temporary}
            ):
                # The message must name the files that are actually absent,
                # not the whole required set.
                self.assertEqual(installer.missing_package_files(), skipped)

    def test_installer_is_available_with_the_complete_package_and_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            _write_package(package)
            script = _write_script(root)
            with mock.patch.dict(
                os.environ,
                {
                    "RC003_WINUHID_PACKAGE": str(package),
                    "RC003_WINUHID_INSTALL_SCRIPT": str(script),
                },
            ):
                self.assertTrue(installer.installer_available())
                self.assertEqual(installer.installer_unavailable_reason(), "")

    def test_installer_reason_names_the_missing_package_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            missing = installer.REQUIRED_PACKAGE_FILES[0]
            _write_package(package, skip=(missing,))
            script = _write_script(root)
            with mock.patch.dict(
                os.environ,
                {
                    "RC003_WINUHID_PACKAGE": str(package),
                    "RC003_WINUHID_INSTALL_SCRIPT": str(script),
                },
            ):
                self.assertFalse(installer.installer_available())
                reason = installer.installer_unavailable_reason()
                self.assertIn("WinUHid 驱动包", reason)
                self.assertIn("fetch-winuhid.ps1", reason)
                self.assertIn(missing, reason)

    def test_installer_reason_names_the_missing_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            _write_package(package)
            with mock.patch.dict(
                os.environ,
                {
                    "RC003_WINUHID_PACKAGE": str(package),
                    "RC003_WINUHID_INSTALL_SCRIPT": str(root / "absent.ps1"),
                },
            ):
                self.assertFalse(installer.installer_available())
                self.assertIn("安装脚本", installer.installer_unavailable_reason())


class ScriptPathTests(unittest.TestCase):
    def test_script_path_follows_the_environment_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            script = _write_script(Path(temporary))
            with mock.patch.dict(
                os.environ, {"RC003_WINUHID_INSTALL_SCRIPT": str(script)}
            ):
                self.assertEqual(Path(installer.script_path()), script)

    def test_script_path_falls_back_to_the_module_script(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RC003_WINUHID_INSTALL_SCRIPT", None)
            path = installer.script_path()
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).is_file())
        self.assertEqual(Path(path).name, installer.SCRIPT_NAME)
        self.assertEqual(Path(path).parent.name, "scripts")


class InstallDriverLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        # Cross-driver exclusivity is covered separately; here it must never
        # touch the machine's real drivers.
        patch = mock.patch.object(installer, "_remove_interception_driver")
        patch.start()
        self.addCleanup(patch.stop)

    def _environment(self, root: Path, *, complete=True):
        package = root / "package"
        _write_package(package, skip=() if complete else installer.REQUIRED_PACKAGE_FILES)
        script = _write_script(root)
        return {
            "RC003_WINUHID_PACKAGE": str(package),
            "RC003_WINUHID_INSTALL_SCRIPT": str(script),
            "LOCALAPPDATA": str(root / "local"),
        }

    def test_install_driver_raises_when_the_package_is_incomplete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.dict(
                os.environ, self._environment(root, complete=False)
            ):
                with self.assertRaises(installer.DriverInstallerError) as caught:
                    installer.install_driver()
            self.assertIn("WinUHid 驱动包", str(caught.exception))

    def test_install_driver_raises_when_the_script_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = self._environment(root)
            environment["RC003_WINUHID_INSTALL_SCRIPT"] = str(root / "absent.ps1")
            with mock.patch.dict(os.environ, environment):
                with self.assertRaises(installer.DriverInstallerError) as caught:
                    installer.install_driver()
            self.assertIn("安装脚本", str(caught.exception))

    def test_install_driver_returns_each_launcher_exit_code(self):
        for exit_code in (0, 3010):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with mock.patch.dict(
                    os.environ, self._environment(root)
                ), mock.patch.object(
                    installer, "_default_launch_elevated", return_value=exit_code
                ) as launch:
                    self.assertEqual(installer.install_driver(), exit_code)
                launch.assert_called_once()
                script, parameters, log_path = launch.call_args.args
                self.assertTrue(Path(script).is_file())
                self.assertIn("-Action Install", parameters)
                self.assertIn("-PackageDir", parameters)
                self.assertTrue(Path(log_path).name.startswith("winuhid-install"))

    def test_install_driver_reports_the_log_path_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.dict(
                os.environ, self._environment(root)
            ), mock.patch.object(
                installer, "_default_launch_elevated", return_value=5
            ):
                with self.assertRaises(installer.DriverInstallerError) as caught:
                    installer.install_driver()
            message = str(caught.exception)
            log_path = Path(root) / "local" / "ovb-rc003" / "logs" / "winuhid-install.log"
            self.assertIn("5", message)
            self.assertIn(str(log_path), message)


class DriverExclusivityTests(unittest.TestCase):
    """Only one virtual-input driver may be installed at a time."""

    def test_installing_removes_the_interception_driver_first(self):
        from ovb_rc003 import interception_driver_install

        with mock.patch(
            "ovb_rc003.interception_runtime_windows.driver_installed",
            return_value=True,
        ), mock.patch.object(
            interception_driver_install, "uninstall_driver"
        ) as uninstall:
            installer._remove_interception_driver()
        uninstall.assert_called_once_with()

    def test_failed_interception_uninstall_aborts_the_install(self):
        from ovb_rc003 import interception_driver_install

        failure = interception_driver_install.DriverInstallerError("boom")
        with mock.patch(
            "ovb_rc003.interception_runtime_windows.driver_installed",
            return_value=True,
        ), mock.patch.object(
            interception_driver_install, "uninstall_driver", side_effect=failure
        ):
            with self.assertRaises(installer.DriverInstallerError):
                installer._remove_interception_driver()


class ElevatedParametersTests(unittest.TestCase):
    def test_elevated_parameters_are_fixed_and_include_install_action(self):
        command = installer._elevated_parameters(
            "C:\\tmp\\install-winuhid.ps1",
            "C:\\tmp\\package",
            "Install",
            "C:\\tmp\\install.log",
        )
        # ``_elevated_parameters`` already returns ``list2cmdline``'s output.
        rendered = command
        self.assertIn("-NoProfile", rendered)
        self.assertIn("-ExecutionPolicy Bypass", rendered)
        self.assertIn("-File", rendered)
        self.assertIn("C:\\tmp\\install-winuhid.ps1", rendered)
        self.assertIn("-Action Install", rendered)
        self.assertIn("-PackageDir", rendered)
        self.assertIn("C:\\tmp\\package", rendered)
        self.assertIn("-LogPath", rendered)
        self.assertIn("C:\\tmp\\install.log", rendered)


class DriverInstalledProbeTests(unittest.TestCase):
    def test_non_windows_returns_none(self):
        with mock.patch.object(installer.sys, "platform", "linux"):
            self.assertIsNone(installer.driver_installed())

    def test_a_winuhid_subkey_means_installed(self):
        fake = _fake_winreg(names=("WINUHID_Keyboard",))
        with mock.patch.object(installer.sys, "platform", "win32"), mock.patch.dict(
            sys.modules, {"winreg": fake}
        ):
            self.assertTrue(installer.driver_installed())

    def test_exhausted_enumeration_means_not_installed(self):
        fake = _fake_winreg(names=())
        with mock.patch.object(installer.sys, "platform", "win32"), mock.patch.dict(
            sys.modules, {"winreg": fake}
        ):
            self.assertFalse(installer.driver_installed())

    def test_an_unopened_registry_means_unknown(self):
        fake = _fake_winreg(open_error=OSError(5, "access denied"))
        with mock.patch.object(installer.sys, "platform", "win32"), mock.patch.dict(
            sys.modules, {"winreg": fake}
        ):
            self.assertIsNone(installer.driver_installed())


if __name__ == "__main__":
    unittest.main()
