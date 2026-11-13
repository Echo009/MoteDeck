"""快速配置弹窗用到的本地环境检测。

两个来源任一命中就算装了输入法——CTF 输入法列表，以及卸载信息，这样用户装了
但还没启用 TSF 也能识别。所有注册表读取都是尽力而为，非 Windows 一律返回
False。

另外提供驱动级按键注入的检测：WinUHid 或 Interception 任一装好，就算第二步
完成；创建驱动级语音键时按实际可用的那个驱动切换注入方式。
"""

from __future__ import annotations

from typing import Dict, Iterator, List, Sequence

from . import tsf_input_windows

try:  # pragma: no cover - Windows-only module, guarded for import safety
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None  # type: ignore[assignment]

# 微信输入法在 TSF 里的名字是 WeType，卸载信息里是「微信输入法」。
_WETYPE_NAME_HINTS = ("wetype", "微信输入法")
# 豆包输入法在 TSF 里就叫「豆包输入法」；卸载信息里还有一条「豆包」。
_DOUBAO_NAME_HINTS = ("豆包输入法", "doubao input", "doubao ime")
# Chatterfly 在 TSF 和卸载信息里都叫 Chatterfly。
_CHATTERFLY_NAME_HINTS = ("chatterfly",)
# OpenMexia / Vokie 是普通桌面应用，只从卸载信息里找。
_OPENMEXIA_NAME_HINTS = ("openmexia",)
_VOKIE_NAME_HINTS = ("vokie",)

_UNINSTALL_PATHS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)

_HIVES = ("HKEY_LOCAL_MACHINE", "HKEY_CURRENT_USER")


def _matches(name: str, hints: Sequence[str]) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in hints)


def _uninstall_display_names() -> Iterator[str]:
    """Every DisplayName under the machine/user uninstall keys."""

    for hive_name in _HIVES:
        hive = getattr(winreg, hive_name, None)
        if hive is None:
            continue
        for path in _UNINSTALL_PATHS:
            try:
                root = winreg.OpenKey(hive, path)
            except OSError:
                continue
            with root:
                index = 0
                while True:
                    try:
                        child = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, child) as entry:
                            value, _ = winreg.QueryValueEx(entry, "DisplayName")
                    except OSError:
                        continue
                    if isinstance(value, str) and value:
                        yield value


def _input_methods(hints: Sequence[str]) -> List[Dict[str, str]]:
    methods: List[Dict[str, str]] = []
    for method in tsf_input_windows.list_input_methods():
        if _matches(str(method.get("name", "")), hints):
            methods.append(method)
    return methods


def _installed(hints: Sequence[str]) -> bool:
    if winreg is None:  # pragma: no cover - non-Windows
        return False
    if _input_methods(hints):
        return True
    return any(_matches(name, hints) for name in _uninstall_display_names())


def wetype_input_methods() -> List[Dict[str, str]]:
    """The WeType entries of the installed TSF input methods."""

    return _input_methods(_WETYPE_NAME_HINTS)


def wetype_installed() -> bool:
    """Whether 微信输入法 is installed on this machine."""

    return _installed(_WETYPE_NAME_HINTS)


def doubao_input_methods() -> List[Dict[str, str]]:
    """The 豆包输入法 entries of the installed TSF input methods."""

    return _input_methods(_DOUBAO_NAME_HINTS)


def doubao_installed() -> bool:
    """Whether 豆包输入法 is installed on this machine."""

    return _installed(_DOUBAO_NAME_HINTS)


def chatterfly_input_methods() -> List[Dict[str, str]]:
    """The Chatterfly entries of the installed TSF input methods."""

    return _input_methods(_CHATTERFLY_NAME_HINTS)


def chatterfly_installed() -> bool:
    """Whether Chatterfly is installed on this machine."""

    return _installed(_CHATTERFLY_NAME_HINTS)


def openmexia_installed() -> bool:
    """Whether OpenMexia is installed on this machine."""

    return _installed(_OPENMEXIA_NAME_HINTS)


def vokie_installed() -> bool:
    """Whether Vokie is installed on this machine."""

    return _installed(_VOKIE_NAME_HINTS)


def input_driver_installed() -> bool:
    """Whether WinUHid or Interception is installed as a driver."""

    from . import interception_runtime_windows, winuhid_driver_install

    for module in (winuhid_driver_install, interception_runtime_windows):
        try:
            if module.driver_installed() is True:
                return True
        except Exception:  # noqa: BLE001 - detection must never break the dialog
            continue
    return False


def installed_driver_inject_mode() -> str:
    """The driver injection mode this machine can actually use.

    WinUHid is preferred when both drivers are installed; ``""`` means neither
    driver can deliver input right now.
    """

    from . import injection_backend

    if injection_backend.winuhid_available():
        return injection_backend.INJECT_MODE_WINUHID
    if injection_backend.interception_available():
        return injection_backend.INJECT_MODE_INTERCEPTION
    return ""
