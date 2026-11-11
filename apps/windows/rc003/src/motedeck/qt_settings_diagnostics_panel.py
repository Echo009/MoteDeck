"""DiagnosticsController (XRBM-031's check-and-repair page bridge).
Mechanically split from
qt_settings_app._load_qt_classes(); only imported lazily from
there, so importing qt_settings_app never requires PySide6."""

from __future__ import annotations

from . import audio_output
from . import bridge_control_windows
from . import bridge_launcher
from . import config
from . import logging_setup
from . import settings_ui
from . import vb_cable_bundle
from . import windows_diagnostics
import threading
from typing import List
from .qt_settings_qml_tokens import (
    Property,
    QObject,
    QTimer,
    Signal,
    Slot,
)
from .qt_settings_app import (
    _AnyEvent,
    _VbCableTestWorkflowResult,
    _diagnostics_shutdown_event,
    _driver_action_active_event,
    _forget_diagnostics_thread,
    _remember_diagnostics_thread,
    _vb_cable_test_active_event,
)


def _diagnostics_check_to_row(check: "windows_diagnostics.CheckResult") -> dict:
    return {
        "checkId": check.check_id,
        "title": check.title,
        "group": check.group.value,
        "status": check.status.value,
        "detail": check.detail,
        "resultCode": check.result_code,
    }

class DiagnosticsController(QObject):
    """QML-facing adapter for the "检查与修复" page (XRBM-031). Every
    check runs off the Qt GUI thread (see module docstring); every
    driver-launch/endpoint-select action is a thin wrapper with no
    business logic of its own, matching SettingsController's contract.
    """

    checkResultsChanged = Signal()
    isRefreshingChanged = Signal()
    diagnosticsErrorMessageChanged = Signal()
    driverStatusMessageChanged = Signal()
    driverInfoMessageChanged = Signal()
    driverErrorMessageChanged = Signal()
    driverActionRunningChanged = Signal()
    vbCableTestChanged = Signal()
    vbCableBridgeRecoveryChanged = Signal()
    # Internal only - never connected to from QML. Carries a
    # windows_diagnostics.DiagnosticsReport (or None on an unexpected
    # worker-thread exception) back from the background thread to this
    # object's own (GUI) thread - see module docstring for why a plain
    # Signal(object) connection is sufficient here.
    _diagnosticsReady = Signal(object)
    _vbCableTestReady = Signal(object)
    _detectedEndpointReady = Signal(object)

    def __init__(
        self,
        settings_controller: "SettingsController",
        config_root,
        parent=None,
        *,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__(parent)
        self._settings_controller = settings_controller
        self._config_root = config_root
        self._is_refreshing = False
        self._check_rows: List[dict] = []
        self._diagnostics_error_message = ""
        self._driver_status_message = ""
        self._driver_info_message = ""
        self._driver_error_message = ""
        self._driver_action_running = False
        self._vb_cable_test_running = False
        self._vb_cable_test_status = "idle"
        self._vb_cable_test_message = ""
        self._vb_cable_bridge_recovery_needed = False
        self._bridge_diagnostics_refresh_pending = False
        self._endpoint_diagnostics_refresh_pending = False
        self._last_bridge_connected = bool(
            self._settings_controller.bridgeConnected
        )
        self._diagnosticsReady.connect(self._on_diagnostics_ready)
        self._vbCableTestReady.connect(self._on_vb_cable_test_ready)
        self._detectedEndpointReady.connect(
            self._on_detected_endpoint_ready
        )
        self._settings_controller.endpointOptionsChanged.connect(
            self._invalidate_vb_cable_test_result
        )
        self._settings_controller.selectedEndpointIndexChanged.connect(
            self._invalidate_vb_cable_test_result
        )
        self._settings_controller.outputEndpointPersisted.connect(
            self._on_output_endpoint_persisted
        )
        self._settings_controller.bridgeConnectedChanged.connect(
            self._on_bridge_connected_changed
        )
        self._settings_controller.bridgeRunningChanged.connect(
            self._on_bridge_running_changed
        )
        self._settings_controller.remoteSelectionChanged.connect(
            self._on_remote_selection_changed
        )
        if auto_refresh:
            self.refreshDiagnostics()

    # -- internal helpers -------------------------------------------------

    def _saved_output_endpoint(self):
        saved_config = config.load_config(config.config_path(self._config_root))
        return (
            saved_config.get("output_endpoint_name", ""),
            saved_config.get("output_endpoint_host_api", ""),
        )

    def _on_remote_selection_changed(self) -> None:
        if self._settings_controller.remoteSelectionBusy:
            return
        current = self._settings_controller.activeRemoteKey
        if current == getattr(self, "_last_remote_selection", None):
            return
        self._last_remote_selection = current
        self._check_rows = []
        self.checkResultsChanged.emit()
        if not self._settings_controller.remoteSelectionBusy:
            self.refreshDiagnostics()

    def _set_driver_status(self, text: str) -> None:
        """Genuine, completed success only (e.g. an endpoint was
        actually selected and persisted) - the only message shown in
        the success/green color. See ``_set_driver_info`` for outcomes
        that are merely informational (XRBM-031 RETRY 1 item 7).
        """

        self._driver_status_message = text
        self._driver_info_message = ""
        self._driver_error_message = ""
        self.driverStatusMessageChanged.emit()
        self.driverInfoMessageChanged.emit()
        self.driverErrorMessageChanged.emit()

    def _set_driver_info(self, text: str) -> None:
        """Neutral, informational outcome - never the success/green
        color: a UAC cancellation installed nothing, and a launched
        vendor setup UI is not yet a confirmed install either (XRBM-031
        RETRY 1 item 7 - "still never say installed until endpoint
        recheck"). QML renders this in a neutral tone, distinct from
        both a real success and a real error.
        """

        self._driver_info_message = text
        self._driver_status_message = ""
        self._driver_error_message = ""
        self.driverInfoMessageChanged.emit()
        self.driverStatusMessageChanged.emit()
        self.driverErrorMessageChanged.emit()

    def _set_driver_error(self, text: str) -> None:
        self._driver_error_message = text
        self._driver_status_message = ""
        self._driver_info_message = ""
        self.driverErrorMessageChanged.emit()
        self.driverStatusMessageChanged.emit()
        self.driverInfoMessageChanged.emit()

    def _set_driver_action_running(self, value: bool) -> None:
        value = bool(value)
        if value:
            _driver_action_active_event.set()
        else:
            _driver_action_active_event.clear()
        if value == self._driver_action_running:
            if not value:
                self._settings_controller._schedule_application_exit_poll()
            return
        self._driver_action_running = value
        self.driverActionRunningChanged.emit()
        if not value:
            self._settings_controller._schedule_application_exit_poll()

    def _set_vb_cable_test_state(
        self, status: str, message: str, *, running: bool
    ) -> None:
        self._vb_cable_test_status = status
        self._vb_cable_test_message = message
        self._vb_cable_test_running = running
        self.vbCableTestChanged.emit()
        if not running and self._bridge_diagnostics_refresh_pending:
            QTimer.singleShot(
                0, self._try_pending_bridge_diagnostics_refresh
            )

    def _set_vb_cable_bridge_recovery_needed(self, value: bool) -> None:
        value = bool(value)
        if value == self._vb_cable_bridge_recovery_needed:
            return
        self._vb_cable_bridge_recovery_needed = value
        self.vbCableBridgeRecoveryChanged.emit()

    def _invalidate_vb_cable_test_result(self) -> None:
        if self._vb_cable_test_running:
            return
        if self._vb_cable_test_status != "idle" or self._vb_cable_test_message:
            self._set_vb_cable_test_state("idle", "", running=False)

    def _on_bridge_connected_changed(self) -> None:
        connected = bool(self._settings_controller.bridgeConnected)
        transitioned_to_connected = connected and not self._last_bridge_connected
        self._last_bridge_connected = connected
        if not connected:
            self._bridge_diagnostics_refresh_pending = False
            return
        if not transitioned_to_connected:
            return
        self._bridge_diagnostics_refresh_pending = True
        QTimer.singleShot(0, self._try_pending_bridge_diagnostics_refresh)

    def _on_bridge_running_changed(self) -> None:
        if (
            not self._settings_controller.bridgeRunning
            or not self._vb_cable_bridge_recovery_needed
        ):
            return
        self._set_vb_cable_bridge_recovery_needed(False)
        self._set_vb_cable_test_state(
            "idle",
            "遥控器服务已重新启动；请重新测试声音通道",
            running=False,
        )

    def _on_output_endpoint_persisted(self) -> None:
        self._endpoint_diagnostics_refresh_pending = True
        QTimer.singleShot(0, self._try_pending_endpoint_diagnostics_refresh)

    def _try_pending_endpoint_diagnostics_refresh(self) -> None:
        if not self._endpoint_diagnostics_refresh_pending:
            return
        if (
            self._is_refreshing
            or self._vb_cable_test_running
            or self._driver_action_running
            or _diagnostics_shutdown_event.is_set()
        ):
            return
        self._endpoint_diagnostics_refresh_pending = False
        self.refreshDiagnostics()

    def _try_pending_bridge_diagnostics_refresh(self) -> None:
        if not self._bridge_diagnostics_refresh_pending:
            return
        if not self._settings_controller.bridgeConnected:
            self._bridge_diagnostics_refresh_pending = False
            return
        if (
            self._is_refreshing
            or self._vb_cable_test_running
            or _diagnostics_shutdown_event.is_set()
        ):
            return
        self._bridge_diagnostics_refresh_pending = False
        self.refreshDiagnostics()

    def _on_diagnostics_ready(self, report) -> None:
        """Delivered (cross-thread) once ``run_diagnostics()`` returns -
        or, if the background thread's own call raised something
        ``windows_diagnostics.run_diagnostics()``'s own per-check
        isolation did not anticipate (should be exceedingly rare now
        that every individual check is isolated - see
        ``windows_diagnostics._isolated()`` - but still possible, e.g.
        if constructing the report itself somehow failed), ``None``.

        XRBM-031 RETRY 1 item 2: a ``None`` report must never leave the
        PREVIOUS run's rows on screen looking current - stale green/red
        rows next to a page that silently failed to refresh would be
        actively misleading. The rows are cleared and a page-level
        error is shown instead, prominently, not only as a driver-card
        message below the fold.
        """

        if (getattr(self, "_diagnostics_selected_remote", self._settings_controller.activeRemoteKey)
                != self._settings_controller.activeRemoteKey):
            self._check_rows = []
            self._is_refreshing = False
            self.checkResultsChanged.emit()
            self.isRefreshingChanged.emit()
            QTimer.singleShot(0, self.refreshDiagnostics)
            return
        if not self._endpoint_diagnostics_refresh_pending:
            if report is not None:
                self._check_rows = [
                    _diagnostics_check_to_row(c) for c in report.checks
                ]
                self._diagnostics_error_message = ""
            else:
                self._check_rows = []
                self._diagnostics_error_message = "检测失败；请重新检测"
        self._is_refreshing = False
        self.checkResultsChanged.emit()
        self.diagnosticsErrorMessageChanged.emit()
        self.isRefreshingChanged.emit()
        if self._bridge_diagnostics_refresh_pending:
            QTimer.singleShot(
                0, self._try_pending_bridge_diagnostics_refresh
            )
        if self._endpoint_diagnostics_refresh_pending:
            QTimer.singleShot(
                0, self._try_pending_endpoint_diagnostics_refresh
            )

    def _on_vb_cable_test_ready(self, result) -> None:
        if result is None:
            self._set_vb_cable_bridge_recovery_needed(False)
            self._set_vb_cable_test_state(
                "fail",
                "通道测试失败；未得到可信结果",
                running=False,
            )
            return
        if isinstance(result, _VbCableTestWorkflowResult):
            if result.stop_error:
                self._set_vb_cable_bridge_recovery_needed(False)
                self._set_vb_cable_test_state(
                    "fail",
                    result.stop_error,
                    running=False,
                )
                self._settings_controller._refresh_bridge_status()
                return
            if result.restart_skipped_for_exit:
                self._set_vb_cable_bridge_recovery_needed(False)
                self._set_vb_cable_test_state(
                    "unsupported",
                    "完全退出中，声音通道测试已停止，服务不再恢复",
                    running=False,
                )
                self._settings_controller._refresh_bridge_status()
                return
            loopback_result = result.loopback_result
            restart_result = result.restart_result
            restart_ok = bool(
                restart_result is not None
                and restart_result.outcome
                in {
                    bridge_launcher.LaunchOutcome.STARTED,
                    bridge_launcher.LaunchOutcome.ALREADY_RUNNING,
                }
            )
            if result.bridge_was_running and not restart_ok:
                self._set_vb_cable_bridge_recovery_needed(True)
                recovery_text = (
                    settings_ui.describe_launch_result(restart_result)
                    if restart_result is not None
                    else "未得到启动结果"
                )
                loopback_text = (
                    loopback_result.detail
                    if loopback_result is not None
                    else "声音通道测试未得到可信结果"
                )
                self._set_vb_cable_test_state(
                    "fail",
                    f"{loopback_text} 遥控器服务未能自动恢复：{recovery_text}",
                    running=False,
                )
                self._settings_controller._refresh_bridge_status()
                return
            self._set_vb_cable_bridge_recovery_needed(False)
            if loopback_result is None:
                self._set_vb_cable_test_state(
                    "fail",
                    "声音通道测试失败；未得到可信结果"
                    + (
                        "；服务已自动恢复"
                        if result.bridge_was_running else ""
                    ),
                    running=False,
                )
            else:
                suffix = (
                    "；服务已自动恢复"
                    if result.bridge_was_running else ""
                )
                self._set_vb_cable_test_state(
                    loopback_result.status.value,
                    loopback_result.detail + suffix,
                    running=False,
                )
            self._settings_controller._refresh_bridge_status()
            return
        self._set_vb_cable_bridge_recovery_needed(False)
        self._set_vb_cable_test_state(
            result.status.value,
            result.detail,
            running=False,
        )

    def _log_sound_channel_diagnostic(self, message: str, *args) -> None:
        try:
            if self._settings_controller._diagnostic_trace_enabled:
                logging_setup.get_logger(self._config_root).info(
                    "sound channel diagnostic: " + message, *args
                )
        except Exception:
            pass  # Logs must not stop the test or its service restoration.

    # -- properties ---------------------------------------------------

    def _get_check_results(self) -> List[dict]:
        return list(self._check_rows)

    checkResults = Property(list, _get_check_results, notify=checkResultsChanged)

    def _get_is_refreshing(self) -> bool:
        return self._is_refreshing

    isRefreshing = Property(bool, _get_is_refreshing, notify=isRefreshingChanged)

    def _get_diagnostics_error_message(self) -> str:
        return self._diagnostics_error_message

    diagnosticsErrorMessage = Property(
        str, _get_diagnostics_error_message, notify=diagnosticsErrorMessageChanged
    )

    def _get_driver_status_message(self) -> str:
        return self._driver_status_message

    driverStatusMessage = Property(
        str, _get_driver_status_message, notify=driverStatusMessageChanged
    )

    def _get_driver_info_message(self) -> str:
        return self._driver_info_message

    driverInfoMessage = Property(
        str, _get_driver_info_message, notify=driverInfoMessageChanged
    )

    def _get_driver_error_message(self) -> str:
        return self._driver_error_message

    driverErrorMessage = Property(
        str, _get_driver_error_message, notify=driverErrorMessageChanged
    )

    driverActionRunning = Property(
        bool,
        lambda self: self._driver_action_running,
        notify=driverActionRunningChanged,
    )

    def _get_vb_cable_test_running(self) -> bool:
        return self._vb_cable_test_running

    vbCableTestRunning = Property(
        bool, _get_vb_cable_test_running, notify=vbCableTestChanged
    )

    def _get_vb_cable_test_status(self) -> str:
        return self._vb_cable_test_status

    vbCableTestStatus = Property(
        str, _get_vb_cable_test_status, notify=vbCableTestChanged
    )

    def _get_vb_cable_test_message(self) -> str:
        return self._vb_cable_test_message

    vbCableTestMessage = Property(
        str, _get_vb_cable_test_message, notify=vbCableTestChanged
    )

    def _get_vb_cable_bridge_recovery_needed(self) -> bool:
        return self._vb_cable_bridge_recovery_needed

    vbCableBridgeRecoveryNeeded = Property(
        bool,
        _get_vb_cable_bridge_recovery_needed,
        notify=vbCableBridgeRecoveryChanged,
    )

    # -- slots ----------------------------------------------------------

    def _emit_diagnostics_ready(self, report) -> None:
        """Thin wrapper around emitting ``_diagnosticsReady``, isolated
        into its own method purely so a test can inject a failure here
        (simulating a receiver/Qt runtime that is already mid-teardown)
        without needing to monkeypatch PySide6's own ``Signal``
        machinery directly. Never called if
        ``_diagnostics_shutdown_event`` is already set when the worker
        checks it - see ``refreshDiagnostics()``'s ``_run_in_background``
        below.
        """

        self._diagnosticsReady.emit(report)

    def _emit_vb_cable_test_ready(self, result) -> None:
        self._vbCableTestReady.emit(result)

    @Slot()
    def startInitialDiagnostics(self) -> None:
        if self._settings_controller.configurationReadOnly:
            return
        if self._check_rows or self._is_refreshing:
            return
        self.refreshDiagnostics()

    @Slot()
    def refreshDiagnostics(self) -> None:
        """Runs every check on a background thread. Repeated clicks
        while a check is already running are ignored outright (the
        guard below), so this can never start two overlapping workers -
        see the module docstring for the full thread-safety/lifecycle
        contract.

        Also refuses to start once process shutdown has begun
        (``_diagnostics_shutdown_event`` set - XRBM-031 RETRY 2): there
        would be nothing left alive to usefully receive this worker's
        result anyway, and starting one so late would only add another
        thread ``_shutdown_qt_settings_app_at_exit()``'s bounded join
        might not have time for.
        """

        if self._settings_controller.configurationReadOnly:
            self._diagnostics_error_message = "配置读取异常，请先导出日志排查；本次未启动设备检查。"
            self.diagnosticsErrorMessageChanged.emit()
            return
        if self._is_refreshing or self._vb_cable_test_running:
            return
        if _diagnostics_shutdown_event.is_set():
            return
        self._invalidate_vb_cable_test_result()
        self._is_refreshing = True
        self.isRefreshingChanged.emit()
        saved_name, saved_host_api = self._saved_output_endpoint()

        selected_remote = self._settings_controller.activeRemoteKey
        self._diagnostics_selected_remote = selected_remote

        def _run_in_background() -> None:
            try:
                try:
                    report = windows_diagnostics.run_diagnostics(
                        saved_output_name=saved_name,
                        saved_output_host_api=saved_host_api,
                        selected_key=selected_remote,
                        # XRBM-035: the SAME event this module's
                        # shutdown helpers set - a discovery attempt
                        # still in flight when the settings window
                        # starts closing is now actually cancelled at
                        # the WinRT level (see
                        # windows_diagnostics._discover_candidates_
                        # cancellable()), not merely abandoned to run
                        # concurrently with interpreter shutdown.
                        cancel_event=_diagnostics_shutdown_event,
                    )
                except Exception:  # noqa: BLE001 - never crash the worker thread
                    report = None
                if _diagnostics_shutdown_event.is_set():
                    # Process shutdown began while this check was
                    # running (XRBM-031 RETRY 2) - the
                    # DiagnosticsController/Qt runtime this would emit
                    # into may already be mid-teardown by now. Skip the
                    # emit entirely rather than race it.
                    return
                try:
                    self._emit_diagnostics_ready(report)
                except Exception:  # noqa: BLE001 - a receiver/Qt runtime
                    # that is ALREADY tearing down despite the check
                    # just above (an inherent, disclosed narrowing-not-
                    # elimination of the race - see module docstring)
                    # must never crash this background thread; the
                    # registry cleanup below still runs regardless.
                    pass
            finally:
                _forget_diagnostics_thread(threading.current_thread())

        thread = threading.Thread(target=_run_in_background, daemon=True)
        _remember_diagnostics_thread(thread)
        thread.start()

    @Slot()
    def testVbCableChannel(self) -> None:
        """Runs the active CABLE Input -> CABLE Output test on demand."""

        self._start_vb_cable_test(allow_bridge_restart=False)

    @Slot()
    def testVbCableChannelWithBridgeRestart(self) -> None:
        """Temporarily stop a running bridge, test, then restore it."""

        self._start_vb_cable_test(allow_bridge_restart=True)

    def _start_vb_cable_test(self, *, allow_bridge_restart: bool) -> None:

        if self._settings_controller.configurationReadOnly:
            self._set_vb_cable_test_state(
                "fail", "配置读取异常，本次未启动声音通道测试。", running=False,
            )
            return
        if self._vb_cable_test_running or self._is_refreshing:
            return
        if _diagnostics_shutdown_event.is_set():
            return
        if (
            self._settings_controller._application_exit_requested
            or self._settings_controller._application_exit_confirmed
            or self._settings_controller._application_exit_intent.is_set()
        ):
            return
        if self._driver_action_running:
            self._set_vb_cable_test_state(
                "fail",
                "输出端点正在处理；完成后再测试声音通道",
                running=False,
            )
            return
        if self._settings_controller._get_voice_hotkey_busy():
            self._set_vb_cable_test_state(
                "fail",
                "语音快捷键正在处理；完成后再测试声音通道",
                running=False,
            )
            return
        if self._settings_controller._get_input_capture_in_use():
            self._set_vb_cable_test_state(
                "fail",
                "按键录入或检测正在进行；结束后再测试声音通道",
                running=False,
            )
            return
        if self._settings_controller._endpoint_preflight_busy:
            self._set_vb_cable_test_state(
                "fail",
                "输出端点正在检查；完成后再测试声音通道",
                running=False,
            )
            return
        if self._settings_controller._get_bridge_launch_busy():
            self._set_vb_cable_test_state(
                "fail",
                "服务正在启动；停止后再测试声音通道",
                running=False,
            )
            return
        bridge_running = self._settings_controller._refresh_bridge_status()
        if bridge_running is None:
            self._set_vb_cable_test_state(
                "unsupported",
                "无法确认服务状态；为避免混入真实语音，未启动测试",
                running=False,
            )
            return
        if bridge_running:
            if not allow_bridge_restart:
                self._set_vb_cable_test_state(
                    "fail",
                    "服务正在运行；需先确认临时停止并自动恢复",
                    running=False,
                )
                return

        saved_name, saved_host_api = self._saved_output_endpoint()
        self._log_sound_channel_diagnostic(
            "phase=start bridge_was_running=%s restore_requested=%s",
            bool(bridge_running), bool(bridge_running and allow_bridge_restart),
        )
        _vb_cable_test_active_event.set()
        self._set_vb_cable_bridge_recovery_needed(False)
        self._set_vb_cable_test_state(
            "running",
            (
                "正在停止服务；随后测试并自动恢复"
                if bridge_running
                else "正在发送测试信号；检查 CABLE Output"
            ),
            running=True,
        )

        def _run_in_background() -> None:
            try:
                stop_error = ""
                loopback_result = None
                restart_result = None
                bridge_stopped = False
                restart_skipped_for_exit = False
                if bridge_running:
                    try:
                        stop_result = bridge_control_windows.request_bridge_exit(reason="audio_test")
                    except Exception:  # noqa: BLE001 - keep the test retryable
                        stop_error = (
                            "无法临时停止遥控器服务；未运行声音通道测试"
                        )
                    else:
                        if not stop_result.stopped:
                            stop_error = stop_result.error or (
                                "未能临时停止服务；未运行声音通道测试"
                            )
                        else:
                            bridge_stopped = True
                try:
                    if (
                        not stop_error
                        and not _diagnostics_shutdown_event.is_set()
                        and not self._settings_controller._application_exit_intent.is_set()
                    ):
                        loopback_result = (
                            windows_diagnostics.check_vb_cable_loopback_isolated(
                                saved_name,
                                saved_host_api,
                                cancel_event=_AnyEvent(
                                    _diagnostics_shutdown_event,
                                    self._settings_controller._application_exit_intent,
                                ),
                            )
                        )
                except Exception:  # noqa: BLE001 - never crash the worker thread
                    loopback_result = None
                finally:
                    if bridge_stopped and (
                        not self._settings_controller._application_exit_intent.is_set()
                        and not _diagnostics_shutdown_event.is_set()
                    ):
                        try:
                            restart_result = (
                                bridge_launcher.launch_in_process_bridge()
                            )
                        except bridge_launcher.BridgeLaunchConfigurationError as exc:
                            restart_result = bridge_launcher.LaunchResult(
                                outcome=bridge_launcher.LaunchOutcome.LAUNCH_FAILED,
                                command=(),
                                error=type(exc).__name__,
                            )
                        except Exception as exc:  # noqa: BLE001 - report recovery failure
                            restart_result = bridge_launcher.LaunchResult(
                                outcome=bridge_launcher.LaunchOutcome.LAUNCH_FAILED,
                                command=(),
                                error=type(exc).__name__,
                            )
                    elif bridge_stopped:
                        restart_skipped_for_exit = True
                result = _VbCableTestWorkflowResult(
                    loopback_result=loopback_result,
                    bridge_was_running=bool(bridge_running),
                    stop_error=stop_error,
                    restart_result=restart_result,
                    restart_skipped_for_exit=restart_skipped_for_exit,
                )
                self._log_sound_channel_diagnostic(
                    "phase=finished bridge_stopped=%s stop_failed=%s "
                    "loopback_status=%s restore_outcome=%s exit_cancelled_restore=%s",
                    bridge_stopped, bool(stop_error),
                    getattr(getattr(loopback_result, 'status', None), 'value', 'unknown'),
                    getattr(getattr(restart_result, 'outcome', None), 'value', 'not_requested'),
                    restart_skipped_for_exit,
                )
                _vb_cable_test_active_event.clear()
                if _diagnostics_shutdown_event.is_set():
                    return
                try:
                    self._emit_vb_cable_test_ready(result)
                except Exception:  # noqa: BLE001 - Qt may already be tearing down
                    pass
            finally:
                _vb_cable_test_active_event.clear()
                _forget_diagnostics_thread(threading.current_thread())

        thread = threading.Thread(target=_run_in_background, daemon=True)
        _remember_diagnostics_thread(thread)
        try:
            thread.start()
        except Exception:
            _forget_diagnostics_thread(thread)
            _vb_cable_test_active_event.clear()
            self._set_vb_cable_test_state(
                "fail",
                "无法启动 VB-CABLE 通道测试后台任务。",
                running=False,
            )

    @Slot(result=bool)
    def selectDetectedCableInputAsOutput(self) -> bool:
        """Detect and save CABLE Input without blocking the Qt thread."""

        if (
            self._vb_cable_test_running
            or self._driver_action_running
            or self._settings_controller._settings_save_busy
            or self._settings_controller._endpoint_preflight_busy
            or self._settings_controller._get_bridge_launch_busy()
            or self._settings_controller._get_voice_hotkey_busy()
            or _diagnostics_shutdown_event.is_set()
            or self._settings_controller._application_exit_requested
            or self._settings_controller._application_exit_intent.is_set()
            or self._settings_controller._application_exit_confirmed
        ):
            return False
        self._invalidate_vb_cable_test_result()
        self._set_driver_action_running(True)
        self._set_driver_info("正在检测并检查 CABLE Input…")

        def run() -> None:
            try:
                endpoints = audio_output.enumerate_output_endpoints()
                matches = [
                    endpoint
                    for endpoint in endpoints
                    if audio_output.is_cable_input_endpoint(endpoint.name)
                ]
                if not matches:
                    payload = (
                        None,
                        "未找到 CABLE Input；请安装 VB-CABLE 并重启电脑",
                    )
                else:
                    try:
                        endpoint = audio_output.select_preferred_output_endpoint(
                            matches
                        )
                    except audio_output.AudioOutputUnavailableError:
                        payload = (
                            None,
                            f"找到 {len(matches)} 个 CABLE Input；"
                            "请在语音页的“输出端点”中选择",
                        )
                    else:
                        payload = (endpoint, "")
            except audio_output.AudioOutputUnavailableError:
                payload = (None, "无法检测播放端点")
            except Exception:  # noqa: BLE001 - keep UI text sanitized
                payload = (None, "播放端点检测失败")
            emitted = self._settings_controller._emit_background_result(
                self._detectedEndpointReady,
                payload,
            )
            if not emitted:
                _driver_action_active_event.clear()

        try:
            self._settings_controller._start_background_task(
                run, "detect-cable-output-endpoint"
            )
        except Exception:
            self._set_driver_action_running(False)
            self._set_driver_error("无法启动播放端点检测")
            return False
        return True

    def _on_detected_endpoint_ready(self, payload: object) -> None:
        if (
            _diagnostics_shutdown_event.is_set()
            or self._settings_controller._application_exit_intent.is_set()
            or self._settings_controller._application_exit_confirmed
        ):
            self._set_driver_action_running(False)
            return
        endpoint, message = payload
        if endpoint is None:
            self._set_driver_action_running(False)
            self._set_driver_error(str(message))
            return

        def finished(ok: bool, error: str) -> None:
            self._set_driver_action_running(False)
            if not ok:
                self._set_driver_error(
                    "输出端点保存失败；"
                    + (error or "请在语音页重新选择")
                )
                return
            self._set_vb_cable_test_state("idle", "", running=False)
            self._set_driver_status(f"已保存输出端点：{endpoint.name}")

        try:
            accepted = self._settings_controller._select_and_persist_output_endpoint(
                endpoint.name,
                endpoint.host_api,
                finished,
                allow_driver_action=True,
            )
        except Exception:  # noqa: BLE001 - keep the async slot retryable
            accepted = False
        if not accepted and self._driver_action_running:
            self._set_driver_action_running(False)
            self._set_driver_error(
                "输出端点保存失败；请在语音页重新选择"
            )

    @Slot()
    def launchVbCableSetup(self) -> None:
        """Launches the bundled VB-CABLE vendor setup UI with UAC. Only
        ever reached from a slot the QML page calls after its OWN
        explicit confirmation dialog (see DiagnosticsPage.qml) - never
        automatically on page load/refresh. Never reports installation
        as successful merely because the process launched; see
        vb_cable_bundle.py's module docstring for the full contract.
        """

        self._set_vb_cable_test_state("idle", "", running=False)
        try:
            vb_cable_bundle.prepare_and_launch_vendor_setup()
        except vb_cable_bundle.BundleNotFoundError as exc:
            self._set_driver_error(f"未找到随包的 VB-CABLE 安装包：{exc}")
        except vb_cable_bundle.UacCancelledError as exc:
            # Neutral/informational, never the success color (XRBM-031
            # RETRY 1 item 7): nothing was installed.
            self._set_driver_info(str(exc))
        except vb_cable_bundle.VbCableBundleError as exc:
            self._set_driver_error(f"启动 VB-CABLE 安装程序失败：{exc}")
        else:
            # Also neutral/informational, not the success color: only
            # that the vendor UI was launched, never a confirmed
            # install - that is only ever established later, by a
            # diagnostics recheck finding both endpoints present.
            self._set_driver_info(
                "已启动 VB-CABLE 程序；请按提示完成安装或卸载并重启电脑后，重新检查"
            )
