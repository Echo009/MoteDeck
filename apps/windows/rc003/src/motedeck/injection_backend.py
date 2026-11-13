"""Per-button injection backend selection.

Every button action is delivered to Windows by injecting input.  There are
three ways to do that, and each button may choose its own:

``sendinput`` (default)
    ``user32!SendInput`` via :mod:`win32_input`.  Works everywhere, but the
    events carry ``LLKHF_INJECTED``, so a target application that deliberately
    ignores synthetic input (some chat clients, games, remote-desktop stacks)
    will not react.

``winuhid``
    A real virtual HID keyboard/mouse built on the WinUHid driver (see
    :mod:`winuhid_windows`).  Reports enter Windows through the ordinary HID
    path, so nothing is flagged as synthetic and applications that ignore
    ``LLKHF_INJECTED`` accept the strokes.  The driver device can only be
    created by an elevated process, so the actual input is submitted by the
    hidden host process (see :mod:`winuhid_host_windows`) - the desktop
    application itself never elevates.  Keys without a keyboard-page usage id
    stay SendInput-only.

``interception``
    The Interception kernel driver via :mod:`interception_runtime_windows`.
    The strokes look exactly like real hardware.  It requires the driver to be
    installed machine-wide (administrator, one reboot) and can only inject keys
    with a stable physical scan code, so a few action kinds stay SendInput-only.

This module is the single place that answers "which backend, and can it do
this action?" - it holds the semantic action -> key-token table and the mode
normalization, and it isolates the driver runtimes so the rest of the app
never touches them directly.
"""

from __future__ import annotations

from typing import Dict, Optional, Protocol, Tuple

from . import (
    interception_runtime_windows,
    key_mapping,
    win32_input,
    win32_keys,
    winuhid_driver_install,
    winuhid_host_windows,
    winuhid_windows,
)

INJECT_MODE_SENDINPUT = key_mapping.DEFAULT_INJECT_MODE
INJECT_MODE_WINUHID = key_mapping.INJECT_MODE_WINUHID
INJECT_MODE_INTERCEPTION = key_mapping.INJECT_MODE_INTERCEPTION
DEFAULT_INJECT_MODE = key_mapping.DEFAULT_INJECT_MODE
INJECT_MODES = key_mapping.INJECT_MODES

INJECT_MODE_LABELS = {
    INJECT_MODE_SENDINPUT: "SendInput（默认）",
    INJECT_MODE_WINUHID: "WinUHid（虚拟键盘）",
    INJECT_MODE_INTERCEPTION: "Interception（驱动级）",
}

# Re-exported so callers can catch an unavailable driver without importing the
# low-level runtime module themselves.
InterceptionUnavailableError = interception_runtime_windows.InterceptionUnavailableError
#: Raised by :class:`WinUHidBackend` when the driver, the elevation prompt or
#: the host process is not usable.
WinUHidUnavailableError = winuhid_windows.WinUHidUnavailableError
#: Anything a driver-level backend may raise because the driver is missing.
DriverUnavailableError = (
    WinUHidUnavailableError,
    InterceptionUnavailableError,
)

# The key sequence each *semantic* action injects.  These are the exact
# tokens the SendInput path already uses (see win32_input.send_show_desktop and
# friends), so both backends stay byte-for-byte equivalent in behaviour.
SEMANTIC_ACTION_KEY_TOKENS: Dict[key_mapping.ActionKind, Tuple[str, ...]] = {
    key_mapping.ActionKind.ESCAPE: ("escape",),
    key_mapping.ActionKind.RETURN: ("enter",),
    key_mapping.ActionKind.ARROW_UP: ("up",),
    key_mapping.ActionKind.ARROW_DOWN: ("down",),
    key_mapping.ActionKind.ARROW_LEFT: ("left",),
    key_mapping.ActionKind.ARROW_RIGHT: ("right",),
    key_mapping.ActionKind.DELETE_BACKWARD: ("backspace",),
    # Win+M, not Win+D: Win+D toggles, so a duplicated remote report would
    # restore every window again (see win32_input.send_show_desktop).
    key_mapping.ActionKind.SHOW_DESKTOP: ("win", "m"),
    key_mapping.ActionKind.CONTEXT_MENU: ("apps",),
    key_mapping.ActionKind.APP_SWITCHER: ("ctrl", "alt", "tab"),
    key_mapping.ActionKind.SYSTEM_VOLUME_UP: ("volume_up",),
    key_mapping.ActionKind.SYSTEM_VOLUME_DOWN: ("volume_down",),
    key_mapping.ActionKind.SYSTEM_VOLUME_MUTE: ("volume_mute",),
    key_mapping.ActionKind.PLAY_PAUSE: ("media_play_pause",),
}

_MOUSE_CLICKS = {
    key_mapping.ActionKind.MOUSE_LEFT_CLICK: "left",
    key_mapping.ActionKind.MOUSE_RIGHT_CLICK: "right",
    key_mapping.ActionKind.MOUSE_MIDDLE_CLICK: "middle",
    key_mapping.ActionKind.MOUSE_X1_CLICK: "x1",
    key_mapping.ActionKind.MOUSE_X2_CLICK: "x2",
}

# Consumer/multimedia controls carry fixed E0-prefixed scan codes (see
# ``win32_input._MULTIMEDIA_SCAN_CODES``) and fixed HID usages, so they are
# injectable like any other key and need no special case here.


def normalize_inject_mode(value: object) -> str:
    """Coerce any stored value to a supported mode, defaulting to SendInput."""

    return key_mapping.normalize_stored_inject_mode(value)


def key_tokens_for_action(action: key_mapping.ButtonAction) -> Optional[Tuple[str, ...]]:
    """Return the ordered key tokens ``action`` injects, or ``None``.

    ``None`` means the action does not inject keys (disabled, URI, open-app,
    element-navigation toggle, voice, mouse, ...).
    """

    if action.kind == key_mapping.ActionKind.KEY_COMBO:
        return tuple(action.keys) or None
    return SEMANTIC_ACTION_KEY_TOKENS.get(action.kind)


def mouse_button_for_action(action: key_mapping.ButtonAction) -> Optional[str]:
    """Return the mouse button ``action`` clicks, or ``None``."""

    return _MOUSE_CLICKS.get(action.kind)


def tokens_supported_by_interception(tokens: Tuple[str, ...]) -> bool:
    """Whether every token resolves to a real physical scan code."""

    if not tokens:
        return False
    for token in tokens:
        try:
            vk_codes = win32_keys.resolve_vk_codes((token,))
        except win32_keys.UnknownKeyTokenError:
            return False
        if not vk_codes or win32_input.physical_scan_code(vk_codes[0]) is None:
            return False
    return True


def action_supported_by_interception(action: key_mapping.ButtonAction) -> bool:
    """Whether ``action`` can be delivered by the Interception backend."""

    tokens = key_tokens_for_action(action)
    if tokens is not None:
        return tokens_supported_by_interception(tokens)
    return mouse_button_for_action(action) is not None


def tokens_supported_by_winuhid(tokens: Tuple[str, ...]) -> bool:
    """Whether every token fits one HID keyboard report (see winuhid_windows)."""

    if not tokens:
        return False
    return winuhid_windows.supports_tokens(tokens)


def action_supported_by_winuhid(action: key_mapping.ButtonAction) -> bool:
    """Whether ``action`` can be delivered by the WinUHid backend."""

    tokens = key_tokens_for_action(action)
    if tokens is not None:
        return tokens_supported_by_winuhid(tokens)
    return mouse_button_for_action(action) is not None


def winuhid_available() -> bool:
    """Whether this machine can currently use the WinUHid backend.

    Two separate things must be true: ``WinUHid.dll`` must ship with this
    build, and the driver must be installed.  Whether the elevation prompt is
    accepted can only be answered by the host process on first use, so that
    stays out of this check.
    """

    if not winuhid_windows.dll_available():
        return False
    return winuhid_driver_install.driver_installed() is not False


def winuhid_unavailable_reason() -> str:
    if winuhid_available():
        return ""
    if not winuhid_windows.dll_available():
        return winuhid_windows.DLL_NOT_FOUND_REASON
    return (
        "driver_not_installed: the WinUHid virtual HID driver is not installed "
        "on this machine"
    )


def _fallback_hint(exclude: str) -> str:
    """Return the options left when the ``exclude`` backend is unusable.

    The other virtual driver is a valid choice too, so a missing backend must
    not claim SendInput is the only option left.
    """

    if exclude != INJECT_MODE_INTERCEPTION and interception_available():
        return "可选 SendInput 或 Interception"
    if exclude != INJECT_MODE_WINUHID and winuhid_available():
        return "可选 SendInput 或 WinUHid"
    return "仅可用 SendInput"


def winuhid_unavailable_hint() -> str:
    """Return the Chinese, user-facing reason WinUHid is unavailable."""

    if winuhid_available():
        return ""
    fallback = _fallback_hint(INJECT_MODE_WINUHID)
    if not winuhid_windows.dll_available():
        return f"缺少 WinUHid.dll，{fallback}"
    return f"未安装 WinUHid 虚拟键盘驱动，{fallback}"


def interception_available() -> bool:
    return interception_runtime_windows.is_available()


def interception_unavailable_reason() -> str:
    return interception_runtime_windows.unavailable_reason()


# User-facing Chinese hints for each reason :func:`interception_unavailable_reason`
# can report.  Matched by stable prefix so extra diagnostics in the suffix still
# map correctly.  A missing DLL or a disabled live-input gate must not be
# misreported as "the driver is not installed".
_UNAVAILABLE_HINTS = (
    ("driver_not_installed", "未检测到 Interception 驱动"),
    ("driver_not_loaded", "Interception 驱动尚未生效，请重启电脑"),
    ("dll_not_found", "缺少 interception.dll"),
    ("create_context_failed", "Interception 驱动上下文创建失败"),
)
# Prefixes whose sentence ends with the list of remaining options.
_FALLBACK_PREFIXES = ("driver_not_installed", "dll_not_found")
_LIVE_INPUT_DISABLED_HINT = "当前进程已禁用实时输入，Interception 暂不可用"


def interception_unavailable_hint() -> str:
    """Return the Chinese, user-facing reason Interception is unavailable.

    Returns ``""`` when the backend is usable.  The settings window binds this
    instead of a fixed "driver not installed" string, so a missing DLL or a
    disabled live-input gate is reported accurately.
    """

    reason = interception_unavailable_reason()
    if not reason:
        return ""
    if "live Windows input is disabled" in reason:
        return _LIVE_INPUT_DISABLED_HINT
    fallback = _fallback_hint(INJECT_MODE_INTERCEPTION)
    for prefix, hint in _UNAVAILABLE_HINTS:
        if reason.startswith(prefix):
            if prefix in _FALLBACK_PREFIXES:
                return f"{hint}，{fallback}"
            return hint
    return f"Interception 暂不可用，{fallback}"


def mode_available(mode: object) -> bool:
    """Whether ``mode`` can currently deliver input on this machine."""

    normalized = normalize_inject_mode(mode)
    if normalized == INJECT_MODE_WINUHID:
        return winuhid_available()
    if normalized == INJECT_MODE_INTERCEPTION:
        return interception_available()
    return True


def mode_status(mode: object) -> Tuple[bool, str]:
    """Return ``(available, reason)`` for one mode, for display in settings."""

    normalized = normalize_inject_mode(mode)
    if normalized == INJECT_MODE_WINUHID:
        available = winuhid_available()
        return available, "" if available else winuhid_unavailable_reason()
    if normalized == INJECT_MODE_INTERCEPTION:
        available = interception_available()
        return available, "" if available else interception_unavailable_reason()
    return True, ""


def send_hold_tokens_down(tokens: Tuple[str, ...]) -> None:
    """Press ``tokens`` in order through the Interception driver.

    The release is not sent: hold-to-talk shortcuts stay owned by the caller
    until the matching :func:`send_hold_tokens_up` call.
    """

    vk_codes = win32_keys.resolve_vk_codes(tokens)
    runtime = interception_runtime_windows.runtime()
    for vk_code in vk_codes:
        runtime.key_down(vk_code)


def send_hold_tokens_up(tokens: Tuple[str, ...]) -> None:
    """Release ``tokens`` in reverse order through the Interception driver."""

    vk_codes = win32_keys.resolve_vk_codes(tokens)
    runtime = interception_runtime_windows.runtime()
    for vk_code in reversed(vk_codes):
        runtime.key_up(vk_code)


def send_hold_tokens_repeat(tokens: Tuple[str, ...]) -> None:
    """Re-send only the held key so typematic repeats keep modifiers down."""

    vk_codes = win32_keys.resolve_vk_codes(tokens)
    if not vk_codes:
        return
    interception_runtime_windows.runtime().key_down(vk_codes[-1])


def send_tokens_via_interception(tokens: Tuple[str, ...]) -> None:
    """Press and release ``tokens`` in order through the Interception driver."""

    send_hold_tokens_down(tokens)
    send_hold_tokens_up(tokens)


def click_mouse_via_interception(button: str) -> None:
    """Click one mouse button through the Interception driver."""

    runtime = interception_runtime_windows.runtime()
    runtime.mouse_button(button, True)
    runtime.mouse_button(button, False)


class InjectionBackend(Protocol):
    """Delivers remote-button input through one injection mechanism.

    Methods take the key tokens the rest of the app already uses, not virtual
    key codes, so both implementations resolve keys the same way.
    """

    name: str

    def key_down(
        self, tokens: Tuple[str, ...], *, require_tracked_hold: bool = True
    ) -> None: ...

    def key_up(self, tokens: Tuple[str, ...]) -> None: ...

    def key_repeat(self, tokens: Tuple[str, ...]) -> None: ...

    def key_tap(self, tokens: Tuple[str, ...]) -> None: ...

    def mouse_click(self, button: str) -> None: ...


class SendInputBackend:
    """``user32!SendInput`` path; events carry ``LLKHF_INJECTED``."""

    name = INJECT_MODE_SENDINPUT

    def key_down(
        self, tokens: Tuple[str, ...], *, require_tracked_hold: bool = True
    ) -> None:
        if require_tracked_hold:
            win32_input.send_voice_key_combo_down(tokens)
            return
        win32_input.send_voice_key_combo_down(
            tokens, require_tracked_hold=False
        )

    def key_up(self, tokens: Tuple[str, ...]) -> None:
        win32_input.send_voice_key_combo_up(tokens)

    def key_repeat(self, tokens: Tuple[str, ...]) -> None:
        win32_input.send_voice_key_combo_repeat(tokens)

    def key_tap(self, tokens: Tuple[str, ...]) -> None:
        win32_input.send_key_combo_tap(tokens)

    def mouse_click(self, button: str) -> None:
        win32_input.send_mouse_button_click(button)


class WinUHidBackend:
    """Virtual HID keyboard/mouse owned by the elevated WinUHid host.

    Every call is one pipe request; the host keeps the devices and their held
    keys, so ``require_tracked_hold`` has no meaning here - the host always
    tracks which tokens are down.
    """

    name = INJECT_MODE_WINUHID

    def _request(self, message: dict) -> None:
        # Never launch the elevated host when the driver is gone: the host would
        # fail immediately and every press would raise another UAC prompt.
        if winuhid_driver_install.driver_installed() is False:
            raise winuhid_windows.WinUHidUnavailableError(
                "未安装 WinUHid 虚拟键盘驱动，WinUHid 注入不可用"
            )
        winuhid_host_windows.ensure_host().request(message)

    def key_down(
        self, tokens: Tuple[str, ...], *, require_tracked_hold: bool = True
    ) -> None:
        self._request({"op": "key_down", "tokens": list(tokens)})

    def key_up(self, tokens: Tuple[str, ...]) -> None:
        self._request({"op": "key_up", "tokens": list(tokens)})

    def key_repeat(self, tokens: Tuple[str, ...]) -> None:
        self._request({"op": "key_repeat", "tokens": list(tokens)})

    def key_tap(self, tokens: Tuple[str, ...]) -> None:
        self._request({"op": "key_tap", "tokens": list(tokens)})

    def mouse_click(self, button: str) -> None:
        self._request({"op": "mouse_click", "button": str(button)})


class InterceptionBackend:
    """Interception kernel driver path; strokes look like real hardware."""

    name = INJECT_MODE_INTERCEPTION

    def key_down(
        self, tokens: Tuple[str, ...], *, require_tracked_hold: bool = True
    ) -> None:
        send_hold_tokens_down(tokens)

    def key_up(self, tokens: Tuple[str, ...]) -> None:
        send_hold_tokens_up(tokens)

    def key_repeat(self, tokens: Tuple[str, ...]) -> None:
        send_hold_tokens_repeat(tokens)

    def key_tap(self, tokens: Tuple[str, ...]) -> None:
        send_tokens_via_interception(tokens)

    def mouse_click(self, button: str) -> None:
        click_mouse_via_interception(button)


_SENDINPUT_BACKEND = SendInputBackend()
_WINUHID_BACKEND = WinUHidBackend()
_INTERCEPTION_BACKEND = InterceptionBackend()


def backend_for(mode: object) -> InjectionBackend:
    """Return the backend for ``mode``; unknown values fall back to SendInput.

    A saved mode outlives the driver it names: the two virtual drivers cannot
    be installed together, so a per-button or per-app mode can still say
    "interception" after WinUHid replaced it.  Delivering through the other
    installed driver keeps those keys working instead of failing outright; the
    requested backend is still returned when no driver can serve it, so the
    caller reports the real reason.
    """

    normalized = normalize_inject_mode(mode)
    if normalized == INJECT_MODE_WINUHID:
        if not winuhid_available() and interception_available():
            return _INTERCEPTION_BACKEND
        return _WINUHID_BACKEND
    if normalized == INJECT_MODE_INTERCEPTION:
        if not interception_available() and winuhid_available():
            return _WINUHID_BACKEND
        return _INTERCEPTION_BACKEND
    return _SENDINPUT_BACKEND
