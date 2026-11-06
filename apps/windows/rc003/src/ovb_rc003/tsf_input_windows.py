"""Switch the session's current TSF input method.

A few voice-input hosts only accept their wake shortcut while their own IME is
the active TSF text service.  A voice key can therefore name one profile to be
activated right before the shortcut is injected (:mod:`app`).

Enumeration reads the installed text services from the CTF registry; activation
goes through ``ITfInputProcessorProfileMgr::ActivateProfile`` with the session
flag, so the switch applies to the foreground application rather than to this
process.  Nothing here is persistent: Windows keeps the last active profile.
"""

from __future__ import annotations

import ctypes
import locale
import os
import sys
from typing import Dict, List, Optional, Tuple

try:  # pragma: no cover - Windows-only module, guarded for import safety
    import winreg
except ImportError:  # pragma: no cover - non-Windows
    winreg = None  # type: ignore[assignment]

# ``TF_PROFILETYPE_INPUTPROCESSOR`` and the flags of ActivateProfile (msctf.h).
TF_PROFILETYPE_INPUTPROCESSOR = 0x0001
TF_IPPMF_FORSESSION = 0x20000000
TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE = 0x00000004

# ``CLSID_TF_InputProcessorProfiles`` creates the profile manager; the interface
# itself is ``IID_ITfInputProcessorProfileMgr``.
_CLSID_TEXT_SERVICE_PROFILES = "{33C53A50-F456-4884-B049-85FD643ECFED}"
_IID_INPUT_PROCESSOR_PROFILE_MGR = "{71C6E74C-0F28-11D8-A82A-00065B84435C}"

_TIP_ROOT = r"SOFTWARE\Microsoft\CTF\TIP"
_LANGUAGE_PROFILE_KEY = "LanguageProfile"
_DESCRIPTION_VALUES = ("Description", "Display Description")


def _require_windows() -> bool:
    return sys.platform == "win32"


def _load_indirect_string(text: str) -> str:
    """Resolve ``@%SystemRoot%\\...,-1234`` descriptions to readable text."""

    if not text.startswith("@"):
        return text
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        result = ctypes.windll.shlwapi.SHLoadIndirectString(  # type: ignore[attr-defined]
            text, buffer, len(buffer), None
        )
        if result == 0 and buffer.value.strip():
            return buffer.value.strip()
    except (AttributeError, OSError):
        pass
    return ""


def _read_string(key, value_name: str) -> str:
    try:
        value = winreg.QueryValueEx(key, value_name)[0]
    except OSError:
        return ""
    if not isinstance(value, str) or not value.strip():
        return ""
    return _load_indirect_string(value.strip())


def _profile_description(key) -> str:
    for value_name in _DESCRIPTION_VALUES:
        text = _read_string(key, value_name)
        if text:
            return text
    return ""


def _read_dword(key, value_name: str) -> int:
    try:
        return int(winreg.QueryValueEx(key, value_name)[0])
    except (OSError, TypeError, ValueError):
        return 0


def _subkey_names(root, path: str) -> List[str]:
    """Return the subkey names below one registry path (empty when missing)."""

    names: List[str] = []
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except OSError:
        pass
    return names


def _parse_langid(text: str) -> Optional[int]:
    """Parse ``0445`` / ``0x00000445`` style language ids."""

    for base in (0, 16):
        try:
            return int(text, base)
        except ValueError:
            continue
    return None


def _clsid_display_name(clsid: str) -> str:
    """Fall back to ``HKCR\\CLSID\\{...}`` when the profile has no description."""

    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, f"CLSID\\{clsid}", 0, winreg.KEY_READ
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return str(value).strip() if isinstance(value, str) else ""
    except OSError:
        return ""


def _executable_path(value: str) -> str:
    """Pull the file path out of an ``InprocServer32`` / ``LocalServer32`` value."""

    text = value.strip()
    if text.startswith('"'):
        end = text.find('"', 1)
        text = text[1:end] if end > 0 else text[1:]
    lowered = text.lower()
    if not lowered.endswith((".dll", ".exe", ".ime")):
        for suffix in (".dll", ".exe", ".ime"):
            index = lowered.find(suffix)
            if index > 0:
                text = text[: index + len(suffix)]
                break
    return os.path.expandvars(text.strip())


def _com_server_path(clsid: str) -> str:
    """Return the DLL/EXE that implements one text service ("" when unknown)."""

    if winreg is None:
        return ""
    for server_key in ("InprocServer32", "LocalServer32"):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                f"CLSID\\{clsid}\\{server_key}",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return _executable_path(value)
    return ""


def _file_company(path: str) -> str:
    """``CompanyName`` from the file's version resource ("" when unavailable)."""

    if not path or not os.path.isfile(path):
        return ""
    try:
        version = ctypes.windll.version  # type: ignore[attr-defined]
        size = version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not version.VerQueryValueW(
            buffer,
            r"\VarFileInfo\Translation",
            ctypes.byref(pointer),
            ctypes.byref(length),
        ):
            return ""
        data = ctypes.string_at(pointer, length.value)
        for offset in range(0, len(data) - 3, 4):
            langid = int.from_bytes(data[offset : offset + 2], "little")
            codepage = int.from_bytes(data[offset + 2 : offset + 4], "little")
            text_pointer = ctypes.c_void_p()
            text_length = ctypes.c_uint()
            query = f"\\StringFileInfo\\{langid:04x}{codepage:04x}\\CompanyName"
            if version.VerQueryValueW(
                buffer,
                query,
                ctypes.byref(text_pointer),
                ctypes.byref(text_length),
            ):
                company = ctypes.wstring_at(text_pointer, text_length.value)
                return company.rstrip("\x00").strip()
    except (AttributeError, OSError, ValueError):
        return ""
    return ""


def _is_builtin(clsid: str) -> bool:
    """Windows 自带：COM 服务器由微软提供。

    判断依据是服务器文件的厂商信息，因为第三方输入法也可能把 DLL 放进
    系统目录（例如腾讯的 Chatterfly 装到 System32）；拼音/五笔这类内置
    IME 没有独立服务器（由系统组件直接实现），同样按内置处理。
    """

    path = _com_server_path(clsid)
    if not path:
        return True
    company = _file_company(path)
    if company:
        return "microsoft" in company.lower()
    system_root = (
        os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    )
    try:
        normalized = os.path.normcase(os.path.abspath(path))
        root_normalized = os.path.normcase(os.path.abspath(system_root))
    except (OSError, ValueError):
        return False
    return normalized.startswith(root_normalized + os.sep)


def _profile_id(langid: int, clsid: str, guid: str) -> str:
    return f"{langid:04X}:{clsid.upper()}:{guid.upper()}"


def _language_name(langid: int) -> str:
    """Readable locale for one language id, e.g. ``zh-CN``; hex otherwise."""

    return locale.windows_locale.get(langid, f"{langid:04X}").replace("_", "-")


def parse_profile_id(profile_id: str) -> Optional[Tuple[int, str, str]]:
    """Split ``langid:clsid:guid`` back into its three activation fields."""

    parts = str(profile_id or "").strip().split(":")
    if len(parts) != 3 or not all(parts):
        return None
    try:
        langid = int(parts[0], 16)
    except ValueError:
        return None
    clsid, guid = parts[1], parts[2]
    if not (clsid.startswith("{") and clsid.endswith("}")):
        return None
    if not (guid.startswith("{") and guid.endswith("}")):
        return None
    return langid, clsid, guid


def _iter_tip_keys(root) -> List[str]:
    """Yield the CLSID key names below one ``CTF\\TIP`` hive."""

    return _subkey_names(root, _TIP_ROOT)


def list_input_methods() -> List[Dict[str, object]]:
    """Return the installed TSF input methods as ``{id, name, language, builtin}``.

    Both machine-wide and per-user text services are listed; duplicates (same
    language id plus CLSID plus profile GUID) are collapsed.  Neutral language
    ids and profiles flagged ``HiddenInSettingUI`` are system components (pen,
    correction, speech), not input methods, so they are skipped.  ``builtin``
    marks the Windows IMEs so the settings dialog can hide them by default.
    """

    if winreg is None or not _require_windows():
        return []
    methods: List[Dict[str, object]] = []
    seen = set()
    builtin_cache: Dict[str, bool] = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for clsid in _iter_tip_keys(hive):
            if not clsid.startswith("{"):
                continue
            if clsid not in builtin_cache:
                builtin_cache[clsid] = _is_builtin(clsid)
            builtin = builtin_cache[clsid]
            languages_path = f"{_TIP_ROOT}\\{clsid}\\{_LANGUAGE_PROFILE_KEY}"
            fallback = _clsid_display_name(clsid)
            for language_key in _subkey_names(hive, languages_path):
                langid = _parse_langid(language_key)
                # 0 表示未指定语言，FFFF 是笔/手写/语音这类中性组件。
                if langid is None or langid in (0x0000, 0xFFFF):
                    continue
                profiles_path = f"{languages_path}\\{language_key}"
                for guid in _subkey_names(hive, profiles_path):
                    if not guid.startswith("{"):
                        continue
                    profile_id = _profile_id(langid, clsid, guid)
                    if profile_id in seen:
                        continue
                    try:
                        with winreg.OpenKey(
                            hive, f"{profiles_path}\\{guid}", 0, winreg.KEY_READ
                        ) as profile_key:
                            # 设置界面里隐藏的是系统内部组件，不作为可选项。
                            if _read_dword(profile_key, "HiddenInSettingUI"):
                                continue
                            name = _profile_description(profile_key)
                    except OSError:
                        continue
                    seen.add(profile_id)
                    methods.append(
                        {
                            "id": profile_id,
                            "name": name or fallback or clsid,
                            "language": _language_name(langid),
                            "builtin": builtin,
                        }
                    )
    methods.sort(key=lambda item: (item["language"], str(item["name"]).lower()))
    return methods


def name_for_profile(profile_id: str) -> str:
    """Return the display name of one profile, or "" when it is not installed."""

    for method in list_input_methods():
        if method["id"] == profile_id:
            return method["name"]
    return ""


def activate(profile_id: str) -> bool:
    """Make one TSF profile the session's current input method.

    Returns False when the profile id is malformed, the interface cannot be
    created, or Windows rejects the activation.  Callers treat False as a
    no-op: the voice shortcut is still attempted.
    """

    parsed = parse_profile_id(profile_id)
    if parsed is None or not _require_windows():
        return False
    langid, clsid, guid = parsed
    try:
        import comtypes
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
        from ctypes import c_uint16, c_uint32, c_void_p

        class ITfInputProcessorProfileMgr(IUnknown):
            _iid_ = GUID(_IID_INPUT_PROCESSOR_PROFILE_MGR)
            _methods_ = [
                COMMETHOD(
                    [],
                    HRESULT,
                    "ActivateProfile",
                    (["in"], c_uint32, "dwProfileType"),
                    (["in"], c_uint16, "langid"),
                    (["in"], GUID, "clsid"),
                    (["in"], GUID, "guidProfile"),
                    (["in"], c_void_p, "hkl"),
                    (["in"], c_uint32, "dwFlags"),
                ),
            ]

        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        manager = comtypes.CoCreateInstance(
            GUID(_CLSID_TEXT_SERVICE_PROFILES),
            interface=ITfInputProcessorProfileMgr,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        manager.ActivateProfile(
            TF_PROFILETYPE_INPUTPROCESSOR,
            langid,
            GUID(clsid),
            GUID(guid),
            None,
            TF_IPPMF_FORSESSION | TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE,
        )
        return True
    except Exception:
        return False
