"""Module-level constants, the cleanup-incomplete exception and the runtime voice hotkey text helper for app.py, mechanically split from app.py's module body (verbatim definitions, zero behavior change); app.py re-exports everything defined here."""

from __future__ import annotations

from .chromecast_voice import TAP_MAX_SECONDS
from . import key_mapping
from .voice_shortcut_session import _VOICE_HOTKEY_BACKEND_MARKED


class CleanupIncompleteError(RuntimeError):
    """Raised when an owned BLE/audio or process-input resource stays live."""

_BUTTON_ACTION_MOUSE_BUTTONS = {
    key_mapping.ActionKind.MOUSE_LEFT_CLICK: "left",
    key_mapping.ActionKind.MOUSE_RIGHT_CLICK: "right",
    key_mapping.ActionKind.MOUSE_MIDDLE_CLICK: "middle",
    key_mapping.ActionKind.MOUSE_X1_CLICK: "x1",
    key_mapping.ActionKind.MOUSE_X2_CLICK: "x2",
}

# Semantic tap mappings only. RC003 physical-edge correlation is separate.
_BUTTON_ACTION_NAVIGATION_VKS = {
    key_mapping.ActionKind.ARROW_UP: 0x26,
    key_mapping.ActionKind.ARROW_DOWN: 0x28,
    key_mapping.ActionKind.ARROW_LEFT: 0x25,
    key_mapping.ActionKind.ARROW_RIGHT: 0x27,
    key_mapping.ActionKind.RETURN: 0x0D,
    key_mapping.ActionKind.ESCAPE: 0x1B,
    key_mapping.ActionKind.CONTEXT_MENU: 0x5D,
    key_mapping.ActionKind.SYSTEM_VOLUME_UP: 0xAF,
    key_mapping.ActionKind.SYSTEM_VOLUME_DOWN: 0xAE,
}

# The remote has no dedicated parent/child actions. A user-mapped, unmodified
# PageUp/PageDown tap keeps those navigation steps available without claiming
# the computer keyboard or changing multi-key shortcut semantics.
_BUTTON_NAVIGATION_SINGLE_KEYS = {
    ("pageup",): 0x21,
    ("page_up",): 0x21,
    ("pagedown",): 0x22,
    ("page_down",): 0x22,
}

# Direction, backspace and volume keys keep the original "连击" behaviour under
# SendInput: a hold replays the whole click (down+up) at the machine's keyboard
# repeat rate, because SendInput cannot emulate the sustained key press a real
# Windows hold produces.  The driver-level backends (WinUHid and Interception)
# do emulate that hold, so the same buttons stay sustained there (see
# ``_begin_button_key_hold``).
_SENDINPUT_CLICK_REPEAT_KINDS = frozenset(
    {
        key_mapping.ActionKind.ARROW_UP,
        key_mapping.ActionKind.ARROW_DOWN,
        key_mapping.ActionKind.ARROW_LEFT,
        key_mapping.ActionKind.ARROW_RIGHT,
        key_mapping.ActionKind.DELETE_BACKWARD,
        key_mapping.ActionKind.SYSTEM_VOLUME_UP,
        key_mapping.ActionKind.SYSTEM_VOLUME_DOWN,
        key_mapping.ActionKind.SYSTEM_VOLUME_MUTE,
    }
)

# An OpenMexia control has no key to hold down: a held button repeats the whole
# action instead.  The bridge request is queued on its own thread, so the repeat
# follows a human-paced interval rather than the machine's keyboard repeat rate
# (30 ms would flood the bridge and leave a long backlog after release).
_OPENMEXIA_HOLD_REPEAT_SECONDS = 0.2

_RAW_FALLBACK_KEY_TOKENS = {
    "mic": "f5",
    "right": "right",
    "left": "left",
    "down": "down",
    "up": "up",
    "ok": "enter",
    "home": "home",
    "menu": "apps",
    "tv": "backtick",
    "power": "vk_5f",
    "volume_mute": "volume_mute",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
    "back": "browser_back",
}

_KEY_DETECTION_MIC_RELEASE_GRACE_SECONDS = 1.0

_KEY_DETECTION_MIC_MAX_SECONDS = 10.0

_ORDINARY_MIC_RELEASE_GUARD_SECONDS = 0.12

_ORDINARY_MIC_SOURCE_STALE_SECONDS = 2.0

_ORDINARY_MIC_MAX_SECONDS = 10.0

_KEY_DETECTION_SUPPRESSION_MAX_SECONDS = 2.0

_RUNTIME_STATUS_HEARTBEAT_SECONDS = 5.0

_PRESET_SWITCH_POLL_SECONDS = 1.0

_VOICE_HOLD_SAFETY_SECONDS = 120.0

# 语音键的短按阈值：按下不到这么久就是短按（只切模式），越过才是长按（语音）。
# 这个值同时也是"延迟发送"的等待窗口，所以它直接决定按下后语音多久才开。
# 0.35 太肉；再往下压就会开始把正常的短按误判成长按。实测 0.15 虽然开口
# 更快，但正常的轻点容易被误判成长按，最终取 0.18。
_VOICE_TAP_MAX_SECONDS = 0.18

# 短按开关（界面上叫"延迟发送"）打开时：按下瞬间一个键都不发，先等满这个
# 短按阈值。窗口内松手只切模式，宿主输入法收不到任何按键，所以短按绝不会
# 变成一次语音输入。只有一直按住、越过这个阈值才是长按，这时才下发那一记
# KEY_DOWN，松手再 KEY_UP。窗口与短按判定共用同一个阈值，两边不会打架。
_VOICE_SHORTCUT_PRESS_DELAY_SECONDS = _VOICE_TAP_MAX_SECONDS

# 谷歌遥控器的语音键要经 BLE 和接收端转发，主机看到的按下→松开比小米实体键
# 长一截：实测正常轻点就有 0.18~0.25 秒，沿用 0.18 的窗口会把一半短按判成
# 长按（于是短按变成一次没反应的语音触发）。这里单独放宽到 0.35 秒，长按
# 实测在 1.2 秒以上，仍然分得干净。
_CHROMECAST_VOICE_TAP_MAX_SECONDS = TAP_MAX_SECONDS

# 插件语音只按"按住多久"分岔，不看音量：按下就开遥控器话筒并把 PCM 缓进
# 一个约 0.8s 的环形缓冲，按满 ``_PLUGIN_VOICE_HOLD_SECONDS`` 才开插件会话
# 并把缓冲一起补发（插件在 session_accepted 之前会自己暂存），所以开口的
# 第一个字不会丢；不到阈值就松手等于短按，只切模式，Vokie 完全不被惊动。
# 用能量判断"有没有说话"会把开话筒的爆音和按键噪声当成人声，连按切模式
# 每次都误触发，所以这里只认时间。
_PLUGIN_VOICE_PREROLL_SECONDS = 0.8

_PLUGIN_VOICE_HOLD_SECONDS = 0.25

# OpenMexia 语音键走本地离线识别：一次最多缓存 55 秒录音，超出的旧声音
# 直接丢掉。和插件键一样，只有按满 ``_OPENMEXIA_ASR_HOLD_SECONDS`` 才开始
# 识别并弹出电平胶囊；不到阈值就松手算短按，照旧切模式。
_OPENMEXIA_ASR_MAX_SECONDS = 55.0

_OPENMEXIA_ASR_HOLD_SECONDS = 0.25

# 松手后继续收这么久的音频：BLE 有传输延迟，立刻关话筒会把最后一个字切掉
# （"调冷" 听起来像 "调了"）。
_OPENMEXIA_ASR_TAIL_SECONDS = 0.3

# 电平胶囊上的波形柱子数：一帧 PCM 切成这么多段，各算峰值。
_OPENMEXIA_ASR_LEVEL_BARS = 9

_VOICE_KEY_PHYSICALIZER_RETRY_SECONDS = 1.0

_VOICE_KEY_PHYSICALIZER_DEGRADED_RETRY_WINDOW_SECONDS = 10.0

_VOICE_KEY_PHYSICALIZER_FAILED_RETRY_SECONDS = 30.0

_RAW_INPUT_RETRY_INITIAL_SECONDS = 1.0

_RAW_INPUT_RETRY_MAX_SECONDS = 30.0

_BUTTON_INPUT_RELEASE_RETRY_INITIAL_SECONDS = 0.1

_BUTTON_INPUT_RELEASE_RETRY_MAX_SECONDS = 2.0

_DIRECTION_BUTTON_IDS = frozenset({"up", "down", "left", "right"})

def _runtime_voice_hotkey_text(config_data: dict) -> str:
    """Configured hold-to-talk shortcut, or "" when the user has not recorded one.

    RC003 no longer fabricates a wake shortcut: an empty value means the voice
    buttons stay inert until the user records 语音一/语音二 in settings.
    """

    return str(config_data.get("voice_hotkey", "")).strip()
