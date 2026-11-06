"""Virtual keyboard and mouse through the WinUHid driver.

WinUHid (https://github.com/cgutman/WinUHid, MIT) creates a *real* HID device
through the Microsoft Virtual HID Framework, so every report this module sends
enters Windows through the same path as a physical keyboard or mouse.  Nothing
carries ``LLKHF_INJECTED``, and applications that deliberately ignore synthetic
input accept the strokes - which is exactly what the optional Interception
backend was for.

Two hard facts shape this module:

* The driver's device object is created by ``\\\\.\\WinUHid``, whose security
  descriptor (see ``WinUHidDriver.inf``) grants access only to Administrators,
  SYSTEM and the user-mode driver.  A normal, non-elevated process cannot even
  probe the driver, let alone create a device.  Creating devices therefore
  belongs to the elevated host process (see :mod:`winuhid_host_windows`); this
  module only speaks to the driver on behalf of whoever already holds it.
* A device belongs to the process that created it and disappears when that
  process exits, so there is no install step beyond the driver itself and no
  state left behind.

Only the report-submission half of the API is bound.  ``SupportedEvents`` is
zero, which tells the driver we accept no host requests (feature reports, LED
writes, ...), so the event poll/complete exports are never needed.

Key tokens are the same tokens the rest of the application already uses (see
:mod:`win32_keys`); they are translated to HID usage ids here, never to
virtual-key codes.  A chord such as ``("ctrl", "alt", "tab")`` is naturally
expressed as "modifier bits + up to six key usages", which is why the keyboard
report descriptor below has the standard 8-byte boot-keyboard layout.

Tokens with no keyboard-page usage id (``browser_back``/``browser_forward``,
whose usages live on the consumer page above 0xFF, and raw ``vk_XX`` tokens)
are rejected instead of being silently dropped.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional, Sequence, Tuple

from . import win32_keys

DLL_ENV_VAR = "RC003_WINUHID_DLL"
DEFAULT_DLL_NAMES = ("WinUHid.dll",)

# pid.codes' shared test vendor id keeps the virtual devices recognizable and
# out of every real vendor's allocated range.
VENDOR_ID = 0x1209
KEYBOARD_PRODUCT_ID = 0x0001
MOUSE_PRODUCT_ID = 0x0002
DEVICE_VERSION = 0x0001

KEYBOARD_INSTANCE_ID = "RC003-Virtual-Keyboard"
MOUSE_INSTANCE_ID = "RC003-Virtual-Mouse"
KEYBOARD_HARDWARE_ID = "HID\\VID_1209&PID_0001&REV_0001"
MOUSE_HARDWARE_ID = "HID\\VID_1209&PID_0002&REV_0001"

# ``WINUHID_DEVICE_CONFIG.SupportedEvents``.  Zero means "this device handles
# no host-initiated requests", which keeps the host process free of the
# WinUHid event loop.
SUPPORTED_EVENTS_NONE = 0

# A press and a release submitted in the same instant can be coalesced by the
# HID stack, so a click holds the button down for one short, human-scale beat.
CLICK_HOLD_SECONDS = 0.02

# Same reason, but a coalesced keystroke is worse: input methods see one state
# change instead of a press and a release and drop the character entirely.
KEY_TAP_HOLD_SECONDS = 0.02

MAX_KEY_CODES_PER_REPORT = 6

# 8-byte boot-style keyboard report: modifier bitmap, one reserved byte, then
# six key usages.  Usage Maximum 0xFF (instead of the usual 0x65) admits the
# keyboard-page volume and media usages the remote's default bindings use.
KEYBOARD_REPORT_DESCRIPTOR = bytes((
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x06,        # Usage (Keyboard)
    0xA1, 0x01,        # Collection (Application)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0xE0,        #   Usage Minimum (Left Control)
    0x29, 0xE7,        #   Usage Maximum (Right GUI)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1)
    0x95, 0x08,        #   Report Count (8)
    0x81, 0x02,        #   Input (Data,Var,Abs)
    0x95, 0x01,        #   Report Count (1)
    0x75, 0x08,        #   Report Size (8)
    0x81, 0x03,        #   Input (Const,Var,Abs)
    0x05, 0x07,        #   Usage Page (Keyboard/Keypad)
    0x19, 0x00,        #   Usage Minimum (0)
    0x2A, 0xFF, 0x00,  #   Usage Maximum (255)
    0x15, 0x00,        #   Logical Minimum (0)
    0x26, 0xFF, 0x00,  #   Logical Maximum (255)
    0x75, 0x08,        #   Report Size (8)
    0x95, 0x06,        #   Report Count (6)
    0x81, 0x00,        #   Input (Data,Array,Abs)
    0xC0,              # End Collection
))

# Relative 3-byte mouse report: five buttons, three padding bits, X and Y.
# Only clicks are needed, so the report carries no motion and no report id.
MOUSE_REPORT_DESCRIPTOR = bytes((
    0x05, 0x01,        # Usage Page (Generic Desktop)
    0x09, 0x02,        # Usage (Mouse)
    0xA1, 0x01,        # Collection (Application)
    0x09, 0x01,        #   Usage (Pointer)
    0xA1, 0x00,        #   Collection (Physical)
    0x05, 0x09,        #     Usage Page (Button)
    0x19, 0x01,        #     Usage Minimum (1)
    0x29, 0x05,        #     Usage Maximum (5)
    0x15, 0x00,        #     Logical Minimum (0)
    0x25, 0x01,        #     Logical Maximum (1)
    0x75, 0x01,        #     Report Size (1)
    0x95, 0x05,        #     Report Count (5)
    0x81, 0x02,        #     Input (Data,Var,Abs)
    0x75, 0x03,        #     Report Size (3)
    0x95, 0x01,        #     Report Count (1)
    0x81, 0x03,        #     Input (Const,Var,Abs)
    0x05, 0x01,        #     Usage Page (Generic Desktop)
    0x09, 0x30,        #     Usage (X)
    0x09, 0x31,        #     Usage (Y)
    0x15, 0x81,        #     Logical Minimum (-127)
    0x25, 0x7F,        #     Logical Maximum (127)
    0x75, 0x08,        #     Report Size (8)
    0x95, 0x02,        #     Report Count (2)
    0x81, 0x06,        #     Input (Data,Var,Rel)
    0xC0,              #   End Collection
    0xC0,              # End Collection
))

# Modifier usage ids become bits in the report's first byte.
_MODIFIER_BITS = {
    "ctrl": 0x01, "lctrl": 0x01,
    "shift": 0x02, "lshift": 0x02,
    "alt": 0x04, "lalt": 0x04,
    "win": 0x08, "lwin": 0x08,
    "rctrl": 0x10,
    "rshift": 0x20,
    "ralt": 0x40,
    "rwin": 0x80,
}

_MOUSE_BUTTON_BITS = {
    "left": 0x01,
    "right": 0x02,
    "middle": 0x04,
    "x1": 0x08,
    "x2": 0x10,
}

# Keyboard/Keypad usage ids (HID Usage Tables, page 0x07).
_KEY_USAGES: Dict[str, int] = {
    "enter": 0x28,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "minus": 0x2D,
    "equals": 0x2E,
    "left_bracket": 0x2F,
    "right_bracket": 0x30,
    "backslash": 0x31,
    "semicolon": 0x33,
    "quote": 0x34,
    "backtick": 0x35,
    "comma": 0x36,
    "period": 0x37,
    "slash": 0x38,
    "caps_lock": 0x39,
    "print_screen": 0x46,
    "scroll_lock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "page_up": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "page_down": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "num_lock": 0x53,
    "numpad_divide": 0x54,
    "numpad_multiply": 0x55,
    "numpad_subtract": 0x56,
    "numpad_add": 0x57,
    "numpad_enter": 0x58,
    "numpad0": 0x62,
    "numpad_decimal": 0x63,
    "apps": 0x65,
    "volume_mute": 0x7F,
    "volume_up": 0x80,
    "volume_down": 0x81,
    "media_next": 0xB5,
    "media_previous": 0xB6,
    "media_stop": 0xB7,
    "media_play_pause": 0xCD,
}

for _ordinal in range(ord("a"), ord("z") + 1):
    _KEY_USAGES[chr(_ordinal)] = 0x04 + (_ordinal - ord("a"))
for _digit in range(1, 10):
    _KEY_USAGES[str(_digit)] = 0x1D + _digit
_KEY_USAGES["0"] = 0x27
for _function in range(1, 13):
    _KEY_USAGES[f"f{_function}"] = 0x39 + _function
for _function in range(13, 25):
    _KEY_USAGES[f"f{_function}"] = 0x67 + (_function - 12)
for _digit in range(1, 10):
    _KEY_USAGES[f"numpad{_digit}"] = 0x58 + _digit

DLL_NOT_FOUND_REASON = (
    f"dll_not_found: place WinUHid.dll next to the app or set {DLL_ENV_VAR}"
)
DRIVER_NOT_AVAILABLE_REASON = (
    "driver_not_available: the WinUHid driver is not installed, or this process "
    "is not allowed to open it (the host must run elevated)"
)


class WinUHidUnavailableError(OSError):
    """Raised when the WinUHid DLL or driver cannot be used."""


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _DeviceConfig(ctypes.Structure):
    """``WINUHID_DEVICE_CONFIG`` (``#include <pshpack1.h>`` in WinUHid.h)."""

    _pack_ = 1
    _fields_ = [
        ("SupportedEvents", ctypes.c_uint32),
        ("VendorID", ctypes.c_uint16),
        ("ProductID", ctypes.c_uint16),
        ("VersionNumber", ctypes.c_uint16),
        ("ReportDescriptorLength", ctypes.c_uint16),
        ("ReportDescriptor", ctypes.c_void_p),
        ("ContainerId", _GUID),
        ("InstanceID", ctypes.c_wchar_p),
        ("HardwareIDs", ctypes.c_wchar_p),
        ("ReadReportPeriodUs", ctypes.c_uint32),
    ]


def _source_tree_asset_dirs() -> List[str]:
    """Return the ignored third-party folder used by source-only runs.

    A frozen build finds the DLL under ``sys._MEIPASS`` (or beside the
    executable in a one-dir build), while a source checkout keeps it in
    ``build/third_party/winuhid``.
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


def _dll_candidate_paths() -> List[str]:
    """Return the DLL locations to try, most specific first."""

    override = os.environ.get(DLL_ENV_VAR, "").strip()
    if override:
        return [override]
    search_dirs: List[str] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        search_dirs.append(str(meipass))
    if getattr(sys, "frozen", False):
        search_dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
    search_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    search_dirs.extend(_source_tree_asset_dirs())
    candidates: List[str] = []
    for directory in search_dirs:
        for name in DEFAULT_DLL_NAMES:
            path = os.path.join(directory, name)
            if path not in candidates:
                candidates.append(path)
    for name in DEFAULT_DLL_NAMES:
        if name not in candidates:
            candidates.append(name)
    return candidates


def _bind(dll) -> None:
    dll.WinUHidGetDriverInterfaceVersion.argtypes = ()
    dll.WinUHidGetDriverInterfaceVersion.restype = ctypes.c_uint32
    dll.WinUHidCreateDevice.argtypes = (ctypes.POINTER(_DeviceConfig),)
    dll.WinUHidCreateDevice.restype = ctypes.c_void_p
    dll.WinUHidStartDevice.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    dll.WinUHidStartDevice.restype = ctypes.c_int
    dll.WinUHidSubmitInputReport.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    dll.WinUHidSubmitInputReport.restype = ctypes.c_int
    dll.WinUHidStopDevice.argtypes = (ctypes.c_void_p,)
    dll.WinUHidStopDevice.restype = None
    dll.WinUHidDestroyDevice.argtypes = (ctypes.c_void_p,)
    dll.WinUHidDestroyDevice.restype = None


_dll_lock = threading.Lock()
_loaded = None


def _load_dll():
    """Load and bind ``WinUHid.dll`` once per process."""

    global _loaded
    with _dll_lock:
        if _loaded is not None:
            return _loaded
        if sys.platform != "win32":
            raise WinUHidUnavailableError("WinUHid is only available on Windows")
        last_error: Optional[OSError] = None
        for candidate in _dll_candidate_paths():
            try:
                dll = ctypes.WinDLL(candidate)  # type: ignore[attr-defined]
            except OSError as exc:
                last_error = exc
                continue
            try:
                _bind(dll)
            except AttributeError as exc:
                last_error = exc
                continue
            _loaded = dll
            return dll
        raise WinUHidUnavailableError(DLL_NOT_FOUND_REASON) from last_error


def driver_interface_version() -> int:
    """Return the driver interface version, or ``0`` when it is unusable.

    The DLL answers ``0`` both when the driver is not installed and when the
    calling process may not open ``\\\\.\\WinUHid``, so this doubles as the
    "am I allowed to create a device?" probe.
    """

    return int(_load_dll().WinUHidGetDriverInterfaceVersion())


def driver_ready() -> bool:
    """Whether this process can talk to an installed WinUHid driver."""

    try:
        return driver_interface_version() > 0
    except (WinUHidUnavailableError, OSError):
        return False


def dll_available() -> bool:
    """Whether ``WinUHid.dll`` is present; needs no elevation to answer."""

    try:
        _load_dll()
    except (WinUHidUnavailableError, OSError):
        return False
    return True


def supports_tokens(tokens: Sequence[str]) -> bool:
    """Whether every token fits one keyboard report."""

    try:
        resolved = [win32_keys.canonical_key_token(str(token)) for token in tokens]
        usages = 0
        for token in resolved:
            bit, usage = _resolve_token(token)
            if not bit:
                usages += 1
    except (win32_keys.UnknownKeyTokenError, ValueError):
        return False
    return usages <= MAX_KEY_CODES_PER_REPORT


def _guid_for(instance_id: str) -> _GUID:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"ovb-rc003-winuhid:{instance_id}")
    guid = _GUID()
    guid.Data1 = value.time_low
    guid.Data2 = value.time_mid
    guid.Data3 = value.time_hi_version
    for index, byte in enumerate(value.bytes[8:]):
        guid.Data4[index] = byte
    return guid


def _resolve_token(token: str) -> Tuple[int, int]:
    """Translate one key token into ``(modifier bit, usage id)``.

    A modifier token yields a non-zero bit and a zero usage; every other token
    yields a zero bit and an 8-bit keyboard-page usage.
    """

    key = win32_keys.canonical_key_token(str(token))
    bit = _MODIFIER_BITS.get(key)
    if bit is not None:
        return bit, 0
    usage = _KEY_USAGES.get(key)
    if usage is None:
        raise win32_keys.UnknownKeyTokenError(
            f"WinUHid 虚拟键盘不支持按键 {token!r}"
        )
    return 0, usage


class _WinUHidDevice:
    """One virtual HID device; created on construction, destroyed on close."""

    def __init__(
        self,
        descriptor: bytes,
        *,
        instance_id: str,
        hardware_id: str,
        product_id: int,
    ) -> None:
        self._lock = threading.RLock()
        self._dll = _load_dll()
        # The descriptor only has to stay alive for the create call, but
        # keeping the buffer referenced makes the lifetimes obvious.
        self._descriptor = ctypes.create_string_buffer(descriptor, len(descriptor))
        config = _DeviceConfig()
        config.SupportedEvents = SUPPORTED_EVENTS_NONE
        config.VendorID = VENDOR_ID
        config.ProductID = product_id
        config.VersionNumber = DEVICE_VERSION
        config.ReportDescriptorLength = len(descriptor)
        config.ReportDescriptor = ctypes.cast(self._descriptor, ctypes.c_void_p)
        config.ContainerId = _guid_for(instance_id)
        config.InstanceID = instance_id
        config.HardwareIDs = hardware_id
        config.ReadReportPeriodUs = 0
        device = self._dll.WinUHidCreateDevice(ctypes.byref(config))
        if not device:
            raise WinUHidUnavailableError(
                "WinUHidCreateDevice failed; the WinUHid driver must be "
                "installed and this process must run elevated"
            )
        self._device = device
        if not self._dll.WinUHidStartDevice(device, None, None):
            self._device = None
            self._dll.WinUHidDestroyDevice(device)
            raise WinUHidUnavailableError("WinUHidStartDevice failed")

    def _submit(self, report: bytes) -> None:
        device = self._device
        if not device:
            raise WinUHidUnavailableError("the WinUHid device is closed")
        buffer = (ctypes.c_ubyte * len(report)).from_buffer_copy(report)
        if not self._dll.WinUHidSubmitInputReport(
            device, ctypes.cast(buffer, ctypes.c_void_p), len(report)
        ):
            raise WinUHidUnavailableError("WinUHidSubmitInputReport failed")

    def close(self) -> None:
        with self._lock:
            device, self._device = self._device, None
            if not device:
                return
            try:
                self._dll.WinUHidStopDevice(device)
            finally:
                self._dll.WinUHidDestroyDevice(device)


class WinUHidKeyboard(_WinUHidDevice):
    """Virtual keyboard that keeps track of which keys are currently held.

    ``key_down`` presses tokens in order and ``key_up`` releases them in
    reverse order, so a chord always reaches Windows with every modifier
    already down - exactly what a physical keyboard does.
    """

    def __init__(
        self,
        *,
        instance_id: str = KEYBOARD_INSTANCE_ID,
        hardware_id: str = KEYBOARD_HARDWARE_ID,
    ) -> None:
        super().__init__(
            KEYBOARD_REPORT_DESCRIPTOR,
            instance_id=instance_id,
            hardware_id=hardware_id,
            product_id=KEYBOARD_PRODUCT_ID,
        )
        self._held: List[str] = []
        # A freshly created HID keyboard starts from "no keys down"; sending
        # that baseline report flushes any stale state in the HID stack.
        self._submit(self._current_report())

    def _current_report(self) -> bytes:
        modifier = 0
        usages: List[int] = []
        for key in self._held:
            bit, usage = _resolve_token(key)
            if bit:
                modifier |= bit
            else:
                usages.append(usage)
        if len(usages) > MAX_KEY_CODES_PER_REPORT:
            raise ValueError(
                f"WinUHid 键盘最多同时按下 {MAX_KEY_CODES_PER_REPORT} 个按键"
            )
        return bytes(
            [modifier, 0x00, *usages, *([0] * (MAX_KEY_CODES_PER_REPORT - len(usages)))]
        )

    def key_down(self, tokens: Sequence[str]) -> None:
        """Press ``tokens``, leaving every one of them held.

        Each token is submitted as its own report, in order, so the chord builds
        up exactly like it would on a physical keyboard.
        """

        resolved = [win32_keys.canonical_key_token(str(token)) for token in tokens]
        for token in resolved:
            _resolve_token(token)
        with self._lock:
            added: List[str] = []
            for token in resolved:
                if token in self._held:
                    continue
                self._held.append(token)
                added.append(token)
                try:
                    self._submit(self._current_report())
                except ValueError:
                    # Never leave a key marked as held that was never sent.
                    for token in added:
                        if token in self._held:
                            self._held.remove(token)
                    raise

    def key_up(self, tokens: Sequence[str]) -> None:
        """Release ``tokens`` in reverse order, one report per token."""

        resolved = [win32_keys.canonical_key_token(str(token)) for token in tokens]
        with self._lock:
            for token in reversed(resolved):
                if token not in self._held:
                    continue
                self._held.remove(token)
                self._submit(self._current_report())

    def key_repeat(self, tokens: Sequence[str]) -> None:
        """Re-press the last non-modifier token.

        A HID keyboard has no typematic repeat of its own, so a held key must
        be released and pressed again - with every modifier still down - for
        the application to see another keystroke.
        """

        resolved = [win32_keys.canonical_key_token(str(token)) for token in tokens]
        with self._lock:
            self.key_down(resolved)
            pressed = [
                token
                for token in resolved
                if token in self._held and not _MODIFIER_BITS.get(token)
            ]
            if not pressed:
                return
            last = pressed[-1]
            self._held.remove(last)
            self._submit(self._current_report())
            self._held.append(last)
            self._submit(self._current_report())

    def key_tap(self, tokens: Sequence[str]) -> None:
        """Press and release ``tokens`` in order.

        A HID report carries *state*, not an event, so submitting the pressed
        and released reports in the same instant lets the stack coalesce them
        into one state change.  Input methods then see no keystroke at all, so
        a tap holds the keys for one short beat before releasing them.
        """

        with self._lock:
            held_before = len(self._held)
            self.key_down(tokens)
            if len(self._held) > held_before:
                time.sleep(KEY_TAP_HOLD_SECONDS)
            self.key_up(tokens)


class WinUHidMouse(_WinUHidDevice):
    """Virtual mouse; only button clicks are needed."""

    def __init__(
        self,
        *,
        instance_id: str = MOUSE_INSTANCE_ID,
        hardware_id: str = MOUSE_HARDWARE_ID,
    ) -> None:
        super().__init__(
            MOUSE_REPORT_DESCRIPTOR,
            instance_id=instance_id,
            hardware_id=hardware_id,
            product_id=MOUSE_PRODUCT_ID,
        )
        self._submit(bytes([0x00, 0x00, 0x00]))

    def click(self, button: str) -> None:
        """Press and release one mouse button."""

        bit = _MOUSE_BUTTON_BITS.get(str(button).strip().lower())
        if bit is None:
            raise ValueError(f"unsupported mouse button: {button}")
        with self._lock:
            self._submit(bytes([bit, 0x00, 0x00]))
            time.sleep(CLICK_HOLD_SECONDS)
            self._submit(bytes([0x00, 0x00, 0x00]))
