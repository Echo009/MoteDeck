"""Install and remove the WinUHid driver behind the virtual keyboard.

The driver itself is a user-mode (UMDF) driver bound to a root-enumerated
device, so installing it is three steps: trust the signing certificate, create
the ``Root\\WinUHid`` device, and stage the driver package onto that device.
:mod:`scripts/install-winuhid.ps1` performs those steps; this module only

* finds the bundled package and script,
* starts the script elevated with fixed arguments (the UAC prompt is the one
  and only interactive step), and
* reports whether the driver ended up installed.

Everything here fails closed: if the package, the script or the elevation is
missing, the caller gets a :class:`DriverInstallerError` with a Chinese reason
instead of a silent "seems fine".
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

INSTALL_SCRIPT_ENV_VAR = "MOTEDECK_WINUHID_INSTALL_SCRIPT"
DRIVER_PACKAGE_ENV_VAR = "MOTEDECK_WINUHID_PACKAGE"

SCRIPT_NAME = "install-winuhid.ps1"
DRIVER_INF_NAME = "WinUHidDriver.inf"

#: Every file the elevated script reads.  Listed here so a half-copied package
#: is rejected before an elevated process is ever started.
REQUIRED_PACKAGE_FILES = (
    DRIVER_INF_NAME,
    "WinUHidDriver.cat",
    "WinUHidDriver.dll",
    "WinUHidCertificate.cer",
)

#: ``DiInstallDriver``/``DiUninstallDriver`` plus a devnode creation finish in
#: a couple of seconds; the timeout only covers a stalled elevated process.
INSTALLER_WAIT_TIMEOUT_SECONDS = 300.0

#: 3010 is "success, reboot required" - not a failure.
_REBOOT_REQUIRED_EXIT_CODE = 3010
_SUCCESS_EXIT_CODES = (0, _REBOOT_REQUIRED_EXIT_CODE)

_DRIVER_ENUM_KEY = r"SYSTEM\CurrentControlSet\Enum\ROOT"
_DRIVER_ENUM_PREFIX = "winuhid"

# SE_ERR_ACCESSDENIED is what Windows reports for a declined UAC prompt; 1223
# is the equivalent GetLastError() value ShellExecuteEx reports.
_SE_ERR_ACCESSDENIED = 5
_UAC_CANCELLED = 1223

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x00000102


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_uint32),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


class DriverInstallerError(RuntimeError):
    """Raised when the bundled WinUHid installer cannot be used."""


class DriverInstallCancelledError(DriverInstallerError):
    """Raised when the user declined the UAC elevation prompt."""


def _source_tree_asset_dirs() -> List[str]:
    """Return the ignored third-party folder used by source-only runs.

    A frozen build finds the package under ``sys._MEIPASS``/the executable
    folder, while a source checkout keeps it in ``build/third_party/winuhid``.
    """

    if getattr(sys, "frozen", False):
        return []
    module_dir = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.normpath(
            os.path.join(
                module_dir,
                os.pardir,
                os.pardir,
                "build",
                "third_party",
                "winuhid",
            )
        )
    ]


def _search_dirs() -> List[str]:
    bases: List[str] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        bases.append(str(meipass))
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
    bases.append(os.path.dirname(os.path.abspath(__file__)))
    bases.extend(_source_tree_asset_dirs())
    # A frozen build collects the package under ``winuhid/`` next to the
    # payload root, so both the base folder and that subfolder are searched.
    directories = list(bases)
    directories.extend(os.path.join(base, "winuhid") for base in bases)
    return directories


def script_path() -> Optional[str]:
    """Return the install script's path, or ``None`` when it is missing."""

    override = os.environ.get(INSTALL_SCRIPT_ENV_VAR, "").strip()
    if override:
        return override if os.path.isfile(override) else None
    for directory in _search_dirs():
        for candidate in (
            os.path.join(directory, SCRIPT_NAME),
            os.path.join(directory, "scripts", SCRIPT_NAME),
        ):
            if os.path.isfile(candidate):
                return candidate
    module_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(module_dir, "scripts", SCRIPT_NAME)
    return candidate if os.path.isfile(candidate) else None


def package_dir() -> Optional[str]:
    """Return the first directory holding a complete driver package."""

    override = os.environ.get(DRIVER_PACKAGE_ENV_VAR, "").strip()
    candidates = [override] if override else _search_dirs()
    for directory in candidates:
        if all(
            os.path.isfile(os.path.join(directory, name))
            for name in REQUIRED_PACKAGE_FILES
        ):
            return directory
    return None


def missing_package_files() -> Tuple[str, ...]:
    """Return the files missing from the most complete candidate folder."""

    override = os.environ.get(DRIVER_PACKAGE_ENV_VAR, "").strip()
    directories = [override] if override else _search_dirs()
    best: Optional[Tuple[str, ...]] = None
    for directory in directories:
        if not os.path.isdir(directory):
            continue
        missing = tuple(
            name
            for name in REQUIRED_PACKAGE_FILES
            if not os.path.isfile(os.path.join(directory, name))
        )
        if not missing:
            return ()
        # Keep looking: another location may hold a more complete package.
        if best is None or len(missing) < len(best):
            best = missing
    return best if best is not None else REQUIRED_PACKAGE_FILES


def installer_available() -> bool:
    """Whether this build ships both the driver package and the script."""

    return script_path() is not None and package_dir() is not None


def installer_unavailable_reason() -> str:
    """Return a Chinese, user-facing reason the installer cannot be used."""

    if script_path() is None:
        return "本次构建未包含 WinUHid 安装脚本（installer_script_not_found）"
    if package_dir() is None:
        missing = ", ".join(missing_package_files())
        return (
            f"本次构建未包含 WinUHid 驱动包（缺少 {missing}）；"
            "请先用 build/fetch-winuhid.ps1 准备驱动包"
        )
    return ""


def driver_installed() -> Optional[bool]:
    """Whether a ``Root\\WinUHid`` device is registered in this machine.

    ``None`` means the registry could not be read at all (non-Windows or a
    locked-down hive), which the settings window reports as "unknown" instead
    of guessing.
    """

    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - only on non-Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DRIVER_ENUM_KEY) as key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    return False
                index += 1
                if name.lower().startswith(_DRIVER_ENUM_PREFIX):
                    return True
    except OSError:
        return None


def driver_state() -> Dict[str, Optional[bool]]:
    """Return ``{"installed": ..., "installer": ...}`` for display."""

    return {"installed": driver_installed(), "installer": installer_available()}


def _log_path(action: str) -> str:
    base = os.environ.get("LOCALAPPDATA", "").strip() or os.path.expanduser("~")
    directory = os.path.join(base, "MoteDeck", "logs")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"winuhid-{action.lower()}.log")


def _powershell_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(
        root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )


def _elevated_parameters(
    script: str, package: str, action: str, log_path: str
) -> str:
    return subprocess.list2cmdline(
        [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
            "-Action",
            action,
            "-PackageDir",
            package,
            "-LogPath",
            log_path,
        ]
    )


def _default_launch_elevated(script: str, parameters: str, log_path: str) -> int:
    """Start ``powershell.exe`` elevated and wait for it to finish."""

    if sys.platform != "win32":
        raise DriverInstallerError("安装 WinUHid 驱动需要 Windows")
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    shell32.ShellExecuteExW.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfo)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = _powershell_path()
    info.lpParameters = parameters
    info.lpDirectory = os.path.dirname(script)
    info.nShow = 0
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.get_last_error()
        if code in (_SE_ERR_ACCESSDENIED, _UAC_CANCELLED):
            raise DriverInstallCancelledError("已取消管理员授权，驱动未安装")
        raise DriverInstallerError(
            f"启动 WinUHid 安装程序失败（ShellExecute 错误码 {code}）"
        )

    try:
        wait = kernel32.WaitForSingleObject(
            info.hProcess, int(INSTALLER_WAIT_TIMEOUT_SECONDS * 1000)
        )
        if wait == _WAIT_TIMEOUT:
            raise DriverInstallerError(
                f"WinUHid 安装程序超过 {int(INSTALLER_WAIT_TIMEOUT_SECONDS)} 秒未结束，"
                f"日志：{log_path}"
            )
        if wait != _WAIT_OBJECT_0:
            raise DriverInstallerError(
                f"等待 WinUHid 安装程序失败（等待结果 {wait}）"
            )
        exit_code = ctypes.c_uint32(1)
        if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code)):
            raise DriverInstallerError("无法读取 WinUHid 安装程序的退出码")
        return int(exit_code.value)
    finally:
        if info.hProcess:
            kernel32.CloseHandle(info.hProcess)


def _run(action: str) -> int:
    script = script_path()
    if script is None:
        raise DriverInstallerError(installer_unavailable_reason())
    package = package_dir()
    if package is None:
        raise DriverInstallerError(installer_unavailable_reason())
    log_path = _log_path(action)
    parameters = _elevated_parameters(script, package, action, log_path)
    exit_code = _default_launch_elevated(script, parameters, log_path)
    if exit_code in _SUCCESS_EXIT_CODES:
        return exit_code
    raise DriverInstallerError(
        f"WinUHid 驱动{'卸载' if action == 'Uninstall' else '安装'}失败"
        f"（退出码 {exit_code}），日志：{log_path}"
    )


def _remove_interception_driver() -> None:
    """Uninstall Interception before installing the virtual keyboard.

    Only one virtual-input driver may be installed at a time: two of them would
    both try to own the same keystrokes.  A refused or failed uninstall aborts
    this install instead of leaving both registered.
    """

    from . import interception_driver_install, interception_runtime_windows

    if interception_runtime_windows.driver_installed() is not True:
        return
    try:
        interception_driver_install.uninstall_driver()
    except interception_driver_install.DriverInstallCancelledError as exc:
        raise DriverInstallCancelledError(
            "需要先卸载 Interception 驱动，但管理员授权被取消，WinUHid 未安装"
        ) from exc
    except interception_driver_install.DriverInstallerError as exc:
        raise DriverInstallerError(
            f"卸载 Interception 驱动失败，WinUHid 未安装：{exc}"
        ) from exc


def install_driver() -> int:
    """Create the device and bind the bundled driver package to it.

    Returns the installer's exit code: ``0`` for a finished install and
    ``3010`` when Windows needs a reboot before the device is usable.
    """

    _remove_interception_driver()
    return _run("Install")


def uninstall_driver() -> int:
    """Remove the device and unstage the driver package."""

    return _run("Uninstall")
