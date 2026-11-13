"""PySide6 imports plus the shared key/token tables for the QML
bridge classes. Mechanically split from
qt_settings_app._load_qt_classes() - the lazy-import contract is
unchanged: importing qt_settings_app itself never requires
PySide6; this module is only imported from inside
_load_qt_classes()."""

from __future__ import annotations

from . import hotkey_capture_windows
from . import win32_keys
import sys


from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QEvent,
    QModelIndex,
    QObject,
    QStandardPaths,
    QTimer,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

_DisplayRole = Qt.ItemDataRole.DisplayRole
_UserRole = Qt.ItemDataRole.UserRole

_QT_MODIFIER_KEY_TOKENS = {
    Qt.Key.Key_Control.value: "ctrl",
    Qt.Key.Key_Shift.value: "shift",
    Qt.Key.Key_Alt.value: "alt",
    Qt.Key.Key_AltGr.value: "alt",
    Qt.Key.Key_Meta.value: "win",
    Qt.Key.Key_Super_L.value: "win",
    Qt.Key.Key_Super_R.value: "win",
}
_QT_MODIFIER_FLAG_TOKENS = (
    (Qt.KeyboardModifier.ControlModifier.value, "ctrl"),
    (Qt.KeyboardModifier.ShiftModifier.value, "shift"),
    (Qt.KeyboardModifier.AltModifier.value, "alt"),
    (Qt.KeyboardModifier.MetaModifier.value, "win"),
)
_QT_SPECIAL_KEY_TOKENS = {
    Qt.Key.Key_Backspace.value: "backspace",
    Qt.Key.Key_Tab.value: "tab",
    Qt.Key.Key_Backtab.value: "tab",
    Qt.Key.Key_Return.value: "enter",
    Qt.Key.Key_Enter.value: "numpad_enter",
    Qt.Key.Key_Escape.value: "escape",
    Qt.Key.Key_Space.value: "space",
    Qt.Key.Key_PageUp.value: "page_up",
    Qt.Key.Key_PageDown.value: "page_down",
    Qt.Key.Key_End.value: "end",
    Qt.Key.Key_Home.value: "home",
    Qt.Key.Key_Left.value: "left",
    Qt.Key.Key_Up.value: "up",
    Qt.Key.Key_Right.value: "right",
    Qt.Key.Key_Down.value: "down",
    Qt.Key.Key_Insert.value: "insert",
    Qt.Key.Key_Delete.value: "delete",
    Qt.Key.Key_Menu.value: "apps",
    Qt.Key.Key_CapsLock.value: "caps_lock",
    Qt.Key.Key_NumLock.value: "num_lock",
    Qt.Key.Key_ScrollLock.value: "scroll_lock",
    Qt.Key.Key_Print.value: "print_screen",
    Qt.Key.Key_Pause.value: "pause",
    Qt.Key.Key_Back.value: "browser_back",
    Qt.Key.Key_Forward.value: "browser_forward",
    Qt.Key.Key_MediaNext.value: "media_next",
    Qt.Key.Key_MediaPrevious.value: "media_previous",
    Qt.Key.Key_MediaStop.value: "media_stop",
    Qt.Key.Key_MediaPlay.value: "media_play_pause",
    Qt.Key.Key_VolumeMute.value: "volume_mute",
    Qt.Key.Key_VolumeDown.value: "volume_down",
    Qt.Key.Key_VolumeUp.value: "volume_up",
}
_QT_KEYPAD_TOKENS = {
    Qt.Key.Key_Plus.value: "numpad_add",
    Qt.Key.Key_Minus.value: "numpad_subtract",
    Qt.Key.Key_Asterisk.value: "numpad_multiply",
    Qt.Key.Key_Slash.value: "numpad_divide",
    Qt.Key.Key_Period.value: "numpad_decimal",
    Qt.Key.Key_Comma.value: "numpad_decimal",
    Qt.Key.Key_Enter.value: "numpad_enter",
    Qt.Key.Key_Return.value: "numpad_enter",
    Qt.Key.Key_Clear.value: "numpad_clear",
    Qt.Key.Key_PageUp.value: "numpad_page_up",
    Qt.Key.Key_PageDown.value: "numpad_page_down",
    Qt.Key.Key_End.value: "numpad_end",
    Qt.Key.Key_Home.value: "numpad_home",
    Qt.Key.Key_Left.value: "numpad_left",
    Qt.Key.Key_Up.value: "numpad_up",
    Qt.Key.Key_Right.value: "numpad_right",
    Qt.Key.Key_Down.value: "numpad_down",
    Qt.Key.Key_Insert.value: "numpad_insert",
    Qt.Key.Key_Delete.value: "numpad_delete",
}

def _qt_hotkey_token(
    key: int,
    text: str,
    modifiers: int,
    *,
    native_virtual_key: int = 0,
    native_scan_code: int = 0,
) -> str:
    key = int(key)
    # A forwarded hook-health probe can also reach Qt. Qt does not retain
    # LLKHF_INJECTED; VK_NONAME is reserved and cannot be a user key here.
    if native_virtual_key == hotkey_capture_windows.VK_NONAME:
        return ""
    keypad_token = (_QT_KEYPAD_TOKENS.get(key)
                    if modifiers & Qt.KeyboardModifier.KeypadModifier.value else None)
    if keypad_token in win32_keys.UNSUPPORTED_KEY_MESSAGES:
        return keypad_token
    # Native identity survives Ctrl control characters, IMEs and layouts.
    # The same decoder is used by the low-level hook and the Qt fallback.
    if sys.platform == "win32" and native_virtual_key:
        flags = (hotkey_capture_windows.LLKHF_EXTENDED
                 if native_scan_code & 0xFF00 == 0xE000 else 0)
        if native_virtual_key == 0x0D and (key == Qt.Key.Key_Enter.value
                                        or modifiers & Qt.KeyboardModifier.KeypadModifier.value):
            flags |= hotkey_capture_windows.LLKHF_EXTENDED
        return hotkey_capture_windows.token_for_keyboard_event(
            native_virtual_key, native_scan_code, flags
        )
    if modifiers & Qt.KeyboardModifier.KeypadModifier.value:
        if keypad_token is not None:
            return keypad_token
        if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
            return f"numpad{chr(key)}"
        return "unsupported_key"
    token = _QT_MODIFIER_KEY_TOKENS.get(key) or _QT_SPECIAL_KEY_TOKENS.get(key)
    if token is not None:
        return token
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F24.value:
        return f"f{key - Qt.Key.Key_F1.value + 1}"
    if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
        return chr(key).lower()
    if 0 <= key <= 0x10ffff:
        symbol = chr(key)
        token = win32_keys.KEY_SYMBOL_TOKENS.get(symbol)
        if token is None and modifiers & Qt.KeyboardModifier.ShiftModifier.value:
            token = win32_keys.KEY_SHIFTED_SYMBOL_TOKENS.get(symbol)
        if token is not None:
            return token
    # Retain an unrecognized edge so a chord cannot silently lose a key.
    return "unsupported_key"
