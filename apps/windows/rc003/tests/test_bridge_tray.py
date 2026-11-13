import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from motedeck import app as app_module
from motedeck import bridge_launcher, bridge_tray_windows


class TrayIconLoadingTests(unittest.TestCase):
    def test_native_api_loads_png_derived_tray_ico_and_releases_handle(self):
        tray = bridge_tray_windows.BridgeTray(
            on_open_settings=lambda: None,
            on_exit_requested=lambda: None,
        )
        user32, shell32, _kernel32 = tray._configure_apis()
        self.assertEqual(user32.LoadImageW.restype, bridge_tray_windows.wintypes.HANDLE)
        try:
            handle = tray._load_icon(user32, shell32)
            self.assertTrue(handle)
            self.assertIn(handle, tray._owned_icons)
        finally:
            for owned in tray._owned_icons:
                self.assertTrue(user32.DestroyIcon(owned))
            tray._owned_icons.clear()

    def test_loads_bundled_ico_before_executable_icon(self):
        tray = bridge_tray_windows.BridgeTray(
            on_open_settings=lambda: None,
            on_exit_requested=lambda: None,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            ico = Path(tmpdir) / "remote-mic-tray.ico"
            ico.write_bytes(b"ico")
            with mock.patch.object(
                bridge_tray_windows.resources, "find_tray_icon", return_value=ico.with_suffix(".png")
            ):
                user32 = mock.Mock()
                user32.LoadImageW.return_value = 456
                shell32 = mock.Mock()
                self.assertEqual(tray._load_icon(user32, shell32), 456)
                user32.LoadImageW.assert_called_once_with(
                    None, str(ico), 1, 16, 16, 0x0010
                )
                shell32.ExtractIconExW.assert_not_called()
                self.assertEqual(tray._owned_icons, [456])

    def test_falls_back_to_system_icon_when_tray_ico_is_missing(self):
        tray = bridge_tray_windows.BridgeTray(
            on_open_settings=lambda: None,
            on_exit_requested=lambda: None,
        )
        user32 = mock.Mock()
        user32.LoadIconW.return_value = 123
        shell32 = mock.Mock()
        with mock.patch.object(
            bridge_tray_windows.resources, "find_tray_icon", return_value=None
        ):
            self.assertEqual(tray._load_icon(user32, shell32), 123)
        shell32.ExtractIconExW.assert_called_once()


class TrayMenuDispatchTests(unittest.TestCase):
    def test_open_settings_command_calls_only_open_callback(self):
        calls = []
        handled = bridge_tray_windows.dispatch_menu_command(
            bridge_tray_windows.MENU_OPEN_SETTINGS,
            on_open_settings=lambda: calls.append("open"),
            on_exit_requested=lambda: calls.append("exit"),
        )
        self.assertTrue(handled)
        self.assertEqual(calls, ["open"])

    def test_exit_command_calls_only_exit_callback(self):
        calls = []
        handled = bridge_tray_windows.dispatch_menu_command(
            bridge_tray_windows.MENU_EXIT_BRIDGE,
            on_open_settings=lambda: calls.append("open"),
            on_exit_requested=lambda: calls.append("exit"),
        )
        self.assertTrue(handled)
        self.assertEqual(calls, ["exit"])

    def test_unknown_command_is_ignored(self):
        calls = []
        handled = bridge_tray_windows.dispatch_menu_command(
            9999,
            on_open_settings=lambda: calls.append("open"),
            on_exit_requested=lambda: calls.append("exit"),
        )
        self.assertFalse(handled)
        self.assertEqual(calls, [])


class _RecordingLogger:
    def __init__(self):
        self.rows = []

    def info(self, message, *args):
        self.rows.append(("info", message, args))

    def warning(self, message, *args):
        self.rows.append(("warning", message, args))

    def exception(self, message, *args):
        self.rows.append(("exception", message, args))


class _FakeBridgeApp:
    def __init__(self):
        self._logger = _RecordingLogger()
        self.started = asyncio.Event()
        self.cancelled = False
        self.stop_calls = 0
        self.reconnect_calls = 0

    async def run_forever(self):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def stop(self):
        self.stop_calls += 1

    def request_connection_retry_now(self):
        self.reconnect_calls += 1


class _FakeTray:
    def __init__(self, **callbacks):
        self.on_open_settings = callbacks["on_open_settings"]
        self.on_exit_requested = callbacks["on_exit_requested"]
        self.status_handler = callbacks["status_handler"]
        self.startup_error = ""
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1
        return True

    def stop(self):
        self.stop_calls += 1
        return True


class BridgeTrayLifecycleTests(unittest.TestCase):
    def test_in_process_runtime_exposes_the_reconnect_callback(self):
        async def scenario():
            fake_app = _FakeBridgeApp()
            callbacks = []
            task = asyncio.create_task(
                app_module._run(
                    app_factory=lambda: fake_app,
                    show_notification_icon=False,
                    on_reconnect_ready=callbacks.append,
                )
            )
            await asyncio.wait_for(fake_app.started.wait(), timeout=1.0)
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            self.assertEqual(fake_app.reconnect_calls, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())

    def test_open_settings_and_exit_are_wired_to_bridge_lifecycle(self):
        async def scenario():
            fake_app = _FakeBridgeApp()
            holder = {}
            settings_calls = []

            def tray_factory(**callbacks):
                tray = _FakeTray(**callbacks)
                holder["tray"] = tray
                return tray

            def launch_settings():
                settings_calls.append(1)
                return bridge_launcher.SettingsLaunchResult(
                    command=("exe", "--settings"),
                    pid=4321,
                )

            task = asyncio.create_task(
                app_module._run(
                    app_factory=lambda: fake_app,
                    tray_factory=tray_factory,
                    settings_launcher=launch_settings,
                )
            )
            await asyncio.wait_for(fake_app.started.wait(), timeout=1.0)
            tray = holder["tray"]
            tray.on_open_settings()
            tray.on_exit_requested()
            await asyncio.wait_for(task, timeout=1.0)

            self.assertEqual(settings_calls, [1])
            self.assertTrue(fake_app.cancelled)
            self.assertEqual(fake_app.stop_calls, 1)
            self.assertEqual(tray.start_calls, 1)
            self.assertEqual(tray.stop_calls, 1)

        asyncio.run(scenario())

    def test_tray_stop_exception_never_skips_bridge_cleanup(self):
        async def scenario():
            fake_app = _FakeBridgeApp()
            holder = {}

            class RaisingStopTray(_FakeTray):
                def stop(self):
                    self.stop_calls += 1
                    raise RuntimeError("simulated tray stop failure")

            def tray_factory(**callbacks):
                tray = RaisingStopTray(**callbacks)
                holder["tray"] = tray
                return tray

            task = asyncio.create_task(
                app_module._run(
                    app_factory=lambda: fake_app,
                    tray_factory=tray_factory,
                )
            )
            await asyncio.wait_for(fake_app.started.wait(), timeout=1.0)
            holder["tray"].on_exit_requested()
            await asyncio.wait_for(task, timeout=1.0)

            self.assertEqual(fake_app.stop_calls, 1)
            self.assertEqual(holder["tray"].stop_calls, 1)
            self.assertTrue(
                any(
                    row[0] == "warning" and "stop failed" in row[1]
                    for row in fake_app._logger.rows
                )
            )

        asyncio.run(scenario())
