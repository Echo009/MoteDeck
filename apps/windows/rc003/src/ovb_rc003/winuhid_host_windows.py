"""Elevated host process that owns the WinUHid virtual keyboard and mouse.

The WinUHid driver only lets Administrators, SYSTEM and the user-mode driver
open ``\\\\.\\WinUHid`` (see ``WinUHidDriver.inf``).  The desktop application
never elevates, so the virtual devices have to live in a separate process that
does.  This module is that process, and it does exactly two things:

1. create the virtual keyboard and mouse once, then
2. replay the reports it is told to send until the parent pipe disappears.

It opens no window, loads no QML, touches no BLE/audio resource and never
starts the desktop application.  The device handles belong to this process
alone, so when it exits the two virtual devices disappear with it - there is
nothing to clean up afterwards and no stale state between runs.

The parent creates the pipe; this host connects to it as a client, which keeps
the pipe at the parent's (ungated) integrity level - an elevated client may
write down to it, while the reverse direction would need a SACL exception.
Before serving a single report the host re-inspects the server process
(pid + start time + user + session, all passed on the command line) so a
same-user squatter cannot borrow this process's elevated input rights.

Protocol (one UTF-8 JSON object per pipe message, request then response)::

    {"op": "key_down", "tokens": ["ctrl", "alt", "tab"]}
    {"op": "key_up", "tokens": ["ctrl", "alt", "tab"]}
    {"op": "key_repeat", "tokens": ["win", "m"]}
    {"op": "key_tap", "tokens": ["escape"]}
    {"op": "mouse_click", "button": "left"}
    {"op": "shutdown"}
    -> {"ok": true} | {"ok": false, "error": "..."}

The host also sends two unsolicited messages: ``{"event": "ready",
"driver_version": <n>}`` once the devices exist, and ``{"event":
"unavailable", "reason": "..."}`` when they could not be created.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from . import dev_session
from . import pipe_windows
from . import winuhid_windows

HOST_FLAG = "--inject-host"

CONNECT_TIMEOUT_SECONDS = 30.0
IDLE_POLL_SECONDS = 0.01
MAX_TOKENS_PER_REQUEST = 8
REQUEST_TIMEOUT_SECONDS = 5.0

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_DRIVER_UNAVAILABLE = 3
EXIT_PROTOCOL_FAILED = 4
EXIT_UNEXPECTED = 5

_GENERATION_PATTERN = re.compile(r"[0-9a-f]{32}")
_KEY_OPS = ("key_down", "key_up", "key_repeat", "key_tap")

_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_FLAG_NO_UI = 0x00000400
_UAC_CANCELLED = 1223


@dataclass(frozen=True)
class _HostArguments:
    """Who asked this host to run, and over which pipe."""

    generation: str
    parent_pid: int
    parent_born: int
    parent_sid: str
    parent_session: int


def encode_message(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parse_arguments(argv: Sequence[str]) -> Optional[_HostArguments]:
    if len(argv) != 5:
        return None
    generation, pid_text, born_text, sid, session_text = (
        str(value).strip() for value in argv
    )
    if not _GENERATION_PATTERN.fullmatch(generation) or not sid:
        return None
    try:
        parent_pid = int(pid_text)
        parent_born = int(born_text)
        parent_session = int(session_text)
    except ValueError:
        return None
    if not 0 < parent_pid <= 0xFFFFFFFF or parent_born <= 0 or parent_session < 0:
        return None
    return _HostArguments(generation, parent_pid, parent_born, sid, parent_session)


def _server_matches(pipe: pipe_windows.Pipe, expected: _HostArguments) -> bool:
    """Refuse to serve reports to anything but the process that launched us."""

    try:
        peer = pipe_windows.inspect_peer(int(pipe.peer_pid()))
    except pipe_windows.PipeError:
        return False
    return (
        peer.pid == expected.parent_pid
        and peer.born == expected.parent_born
        and peer.sid == expected.parent_sid
        and peer.session == expected.parent_session
    )


def _send(pipe: pipe_windows.Pipe, message: dict) -> bool:
    try:
        pipe.write(encode_message(message))
    except pipe_windows.PipeError:
        return False
    return True


def _tokens(message: dict) -> Tuple[str, ...]:
    raw = message.get("tokens")
    if not isinstance(raw, list) or not raw or len(raw) > MAX_TOKENS_PER_REQUEST:
        raise ValueError("tokens must be a non-empty list")
    tokens = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("tokens must be key names")
        tokens.append(item)
    return tuple(tokens)


def _dispatch(
    message: dict,
    keyboard: winuhid_windows.WinUHidKeyboard,
    mouse: winuhid_windows.WinUHidMouse,
) -> None:
    op = message.get("op")
    if op in _KEY_OPS:
        getattr(keyboard, op)(_tokens(message))
        return
    if op == "mouse_click":
        button = message.get("button")
        if not isinstance(button, str):
            raise ValueError("button must be a mouse button name")
        mouse.click(button)
        return
    raise ValueError(f"unknown op: {op!r}")


def _serve(
    pipe: pipe_windows.Pipe,
    keyboard: winuhid_windows.WinUHidKeyboard,
    mouse: winuhid_windows.WinUHidMouse,
) -> int:
    while True:
        try:
            frame = pipe.read()
        except pipe_windows.PipeError:
            # The parent closed the pipe: this host has nothing left to serve.
            return EXIT_OK
        if frame is None:
            time.sleep(IDLE_POLL_SECONDS)
            continue
        try:
            message = json.loads(frame.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            if not _send(pipe, {"ok": False, "error": "invalid message"}):
                return EXIT_OK
            continue
        if not isinstance(message, dict):
            if not _send(pipe, {"ok": False, "error": "invalid message"}):
                return EXIT_OK
            continue
        if message.get("op") == "shutdown":
            _send(pipe, {"ok": True})
            return EXIT_OK
        try:
            _dispatch(message, keyboard, mouse)
        except (ValueError, winuhid_windows.WinUHidUnavailableError) as exc:
            if not _send(pipe, {"ok": False, "error": str(exc)}):
                return EXIT_OK
        else:
            if not _send(pipe, {"ok": True}):
                return EXIT_OK


def _run(arguments: _HostArguments) -> int:
    identity = pipe_windows.SessionIdentity("winuhid-host", arguments.generation, "")
    pipe = pipe_windows.Pipe(identity, server=False)
    cancel = threading.Event()
    try:
        try:
            pipe.connect(time.monotonic() + CONNECT_TIMEOUT_SECONDS, cancel)
        except pipe_windows.PipeError:
            return EXIT_PROTOCOL_FAILED
        if not _server_matches(pipe, arguments):
            return EXIT_PROTOCOL_FAILED
        try:
            keyboard = winuhid_windows.WinUHidKeyboard()
            mouse = winuhid_windows.WinUHidMouse()
        except OSError as exc:
            _send(pipe, {"event": "unavailable", "reason": str(exc)})
            return EXIT_DRIVER_UNAVAILABLE
        try:
            version = winuhid_windows.driver_interface_version()
            if not _send(pipe, {"event": "ready", "driver_version": version}):
                return EXIT_OK
            return _serve(pipe, keyboard, mouse)
        finally:
            keyboard.close()
            mouse.close()
    finally:
        try:
            pipe.close()
        except pipe_windows.PipeError:
            pass


def host_main(argv: Sequence[str]) -> int:
    """Run the elevated injection host; returns a process exit code."""

    arguments = _parse_arguments(argv)
    if arguments is None:
        return EXIT_USAGE
    try:
        return _run(arguments)
    except Exception as exc:  # never fall through to anything resembling startup
        print(f"winuhid injection host failed: {type(exc).__name__}", file=sys.stderr)
        return EXIT_UNEXPECTED


# -- parent side -----------------------------------------------------------
# The desktop process never elevates.  It creates the pipe, asks Windows to
# launch its own executable with ``--inject-host`` through the ``runas`` verb
# (one UAC prompt), then drives the host with the protocol above.


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


def _host_command(arguments: _HostArguments) -> list:
    """This distribution's own executable, never a caller-supplied path."""

    command = (
        []
        if getattr(sys, "frozen", False)
        else [str(Path(__file__).resolve().parents[1] / "launcher.py")]
    )
    command += [
        HOST_FLAG,
        arguments.generation,
        str(arguments.parent_pid),
        str(arguments.parent_born),
        arguments.parent_sid,
        str(arguments.parent_session),
    ]
    return dev_session.mark_command(command)


def _launch_host(arguments: _HostArguments) -> int:
    """Start the elevated host and return its pid."""

    if sys.platform != "win32":
        raise winuhid_windows.WinUHidUnavailableError(
            "WinUHid 注入宿主只能在 Windows 上运行"
        )
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(_ShellExecuteInfo),)
    shell32.ShellExecuteExW.restype = ctypes.c_int
    kernel32.GetProcessId.argtypes = (ctypes.c_void_p,)
    kernel32.GetProcessId.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_FLAG_NO_UI
    info.lpVerb = "runas"
    info.lpFile = sys.executable
    info.lpParameters = subprocess.list2cmdline(_host_command(arguments))
    info.nShow = 0
    ctypes.set_last_error(0)
    if not shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        error = int(ctypes.get_last_error())
        if error == _UAC_CANCELLED:
            raise winuhid_windows.WinUHidUnavailableError(
                "已取消管理员授权，WinUHid 注入未启动"
            )
        raise winuhid_windows.WinUHidUnavailableError(
            f"无法启动 WinUHid 注入宿主（错误 {error}）"
        )
    try:
        return int(kernel32.GetProcessId(info.hProcess))
    finally:
        kernel32.CloseHandle(info.hProcess)


class WinUHidHost:
    """Parent-side handle to the elevated host, one per desktop process."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pipe = None
        self._ready = False

    @property
    def running(self) -> bool:
        return self._ready

    def _read_message(self, pipe, deadline: float) -> dict:
        while time.monotonic() < deadline:
            frame = pipe.read()
            if frame is None:
                time.sleep(0.002)
                continue
            return json.loads(frame.decode("utf-8"))
        raise winuhid_windows.WinUHidUnavailableError("WinUHid 注入宿主启动超时")

    def ensure_started(self) -> None:
        """Launch and verify the host, raising a readable error on failure."""

        with self._lock:
            if self._ready:
                return
            parent = pipe_windows.inspect_peer(os.getpid())
            generation = uuid.uuid4().hex
            arguments = _HostArguments(
                generation, parent.pid, parent.born, parent.sid, parent.session
            )
            identity = pipe_windows.SessionIdentity("winuhid-host", generation, "")
            pipe = pipe_windows.Pipe(identity, server=True)
            try:
                launched = pipe_windows.inspect_peer(_launch_host(arguments))
                deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
                pipe.connect(deadline, threading.Event())
                # Refuse to serve a pipe that is not the process we launched.
                from .chromecast_pipe_windows import verify_worker_peer

                verify_worker_peer(
                    pipe_windows.inspect_peer(int(pipe.peer_pid())), launched, parent
                )
                hello = self._read_message(pipe, deadline)
            except winuhid_windows.WinUHidUnavailableError:
                try:
                    pipe.close()
                except pipe_windows.PipeError:
                    pass
                raise
            except (pipe_windows.PipeError, OSError, ValueError) as exc:
                try:
                    pipe.close()
                except pipe_windows.PipeError:
                    pass
                raise winuhid_windows.WinUHidUnavailableError(
                    f"WinUHid 注入宿主没有就绪：{exc}"
                ) from exc
            if hello.get("event") != "ready":
                reason = str(hello.get("reason") or "WinUHid 注入宿主没有就绪")
                try:
                    pipe.close()
                except pipe_windows.PipeError:
                    pass
                raise winuhid_windows.WinUHidUnavailableError(reason)
            self._pipe = pipe
            self._ready = True

    def _fail(self) -> None:
        pipe, self._pipe = self._pipe, None
        self._ready = False
        if pipe is None:
            return
        try:
            pipe.close()
        except pipe_windows.PipeError:
            pass

    def request(self, message: dict, timeout: float = REQUEST_TIMEOUT_SECONDS) -> dict:
        """Send one request and return the host's answer."""

        with self._lock:
            self.ensure_started()
            pipe = self._pipe
            try:
                pipe.write(encode_message(message))
                deadline = time.monotonic() + timeout
                while True:
                    frame = pipe.read()
                    if frame is None:
                        if time.monotonic() >= deadline:
                            raise winuhid_windows.WinUHidUnavailableError(
                                "WinUHid 注入宿主没有响应"
                            )
                        time.sleep(0.002)
                        continue
                    response = json.loads(frame.decode("utf-8"))
                    if "event" in response:
                        continue
                    break
            except winuhid_windows.WinUHidUnavailableError:
                raise
            except (pipe_windows.PipeError, OSError, ValueError) as exc:
                self._fail()
                raise winuhid_windows.WinUHidUnavailableError(
                    f"WinUHid 注入宿主已断开：{exc}"
                ) from exc
            if not response.get("ok"):
                raise winuhid_windows.WinUHidUnavailableError(
                    str(response.get("error") or "WinUHid 注入失败")
                )
            return response

    def close(self) -> None:
        with self._lock:
            pipe, self._pipe = self._pipe, None
            self._ready = False
            if pipe is None:
                return
            try:
                pipe.write(encode_message({"op": "shutdown"}))
            except pipe_windows.PipeError:
                pass
            try:
                pipe.close()
            except pipe_windows.PipeError:
                pass


_client_lock = threading.Lock()
_client: Optional[WinUHidHost] = None


def ensure_host() -> WinUHidHost:
    """The desktop process's single host handle."""

    global _client
    with _client_lock:
        if _client is None:
            _client = WinUHidHost()
        return _client


def reset_host() -> None:
    """Forget the cached host so the next request reopens the current device.

    Uninstalling the driver destroys the device.  A host started before the
    reinstall keeps a handle Windows no longer delivers to, so every injected
    report would be silently lost until the whole application restarts.
    """

    global _client
    with _client_lock:
        client, _client = _client, None
    if client is not None:
        client.close()
