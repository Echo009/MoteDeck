"""Build-only inventory shared by compilation and freezing, never shipped.

Source files are authoritative; only the tiny package initializer and EXE
launchers stay as Python glue. Navigation uses the same sources as OrthoFocus.
"""
from __future__ import annotations
import ast
from pathlib import Path

NAVIGATION_MODULES = (
    "element_navigation_prototype", "element_navigation_command_windows",
    "element_navigation_support", "element_navigation_windows_host",
    "element_targeting_core", "spatial_navigation_core",
)
LEGACY_MODULES = (
    "motedeck.hid_elevation_windows", "motedeck.hid_helper_consumers",
)
# 智慧应用控制（SAC）只拦未签名的原生二进制（exe/dll/pyd），不碰纯字节码。
# Frida HID 通道（小米遥控器返回键、音量键）依赖这些模块，把它们保留为
# Python 源码后由 PyInstaller 打进 PYZ 变成 .pyc，SAC 就没有可拦截的 .pyd。
PYTHON_ONLY_MODULES = (
    "motedeck.hid_host_reload_windows",
    "motedeck.frida_hid_tap_injector",
    "motedeck.frida_hid_tap_runtime",
    "motedeck.gadget_windows",
    "motedeck.frida_compat",
    "motedeck.hid_source_injector",
    "motedeck.hid_injection_diagnostics",
)
# CPython's -m loader needs a Python code object. Keep only this generated
# bootstrap as Python; the complete original entrypoint is compiled.
MAIN_BOOTSTRAP = """import sys
from . import _native_main
if __name__ == "__main__":
    _native_main.main()
else:
    sys.modules[__name__] = _native_main
"""


def module_sources(root: Path) -> dict[str, Path]:
    result = {}
    for source in sorted((root / "src" / "motedeck").rglob("*.py")):
        if source.name != "__init__.py":
            name = ".".join(source.relative_to(root / "src").with_suffix("").parts)
            if name == "motedeck.__main__":
                name = "motedeck._native_main"
            if name in result:
                raise ValueError(f"native module name collision: {name}")
            result[name] = source
    for name in NAVIGATION_MODULES:
        source = root / "scripts" / f"{name}.py"
        if not source.is_file():
            raise FileNotFoundError(source)
        result[name] = source
    return result


def compiled_module_sources(root: Path) -> dict[str, Path]:
    """module_sources() minus the modules shipped as bytecode instead of .pyd."""
    return {name: source for name, source in module_sources(root).items()
            if name not in PYTHON_ONLY_MODULES}


def import_closure(root: Path, seeds: list[str] | None = None,
                   excludes: tuple[str, ...] = ()) -> list[str]:
    """Capture imports before Cython hides them from the bytecode scanner.

Literal optional/lazy imports are included. Generated imports still belong in
the spec's explicit list. Helper closure follows only its own entry modules.
"""
    sources = module_sources(root)
    pending = list(sources if seeds is None else seeds)
    seen = set()
    while pending:
        name = pending.pop()
        if any(name == item or name.startswith(item + ".") for item in excludes):
            continue
        if name.startswith("motedeck.") and name not in sources:
            continue  # e.g. 'from . import __version__' imports a value.
        if name in seen:
            continue
        seen.add(name)
        source = sources.get(name)
        if source is None:
            continue
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = name.split(".")[:-node.level]
                    if node.module:
                        pending.append(".".join(base + node.module.split(".")))
                    else:
                        pending.extend(".".join(base + [a.name]) for a in node.names)
                elif node.module:
                    pending.append(node.module)
    return sorted(seen - {"__future__"})


# Sources that shape the narrow HID helper. A change here alters the helper
# binary, so the shipped HELPER_GENERATION must be raised or upgraded installs
# will keep reusing the previous helper. Shared by the PyInstaller spec and
# build/check-helper-generation.py so both agree on the same file set.
HELPER_SEEDS = (
    "motedeck.hid_elevation_windows",
    "motedeck.frida_hid_tap_injector",
)
HELPER_EXCLUDES = (
    "PySide6", "numpy", "sounddevice", "winrt", "uiautomation",
    "motedeck.app", "motedeck.qt_settings_app", "motedeck.ble_transport_winrt",
    "motedeck.audio_playback", "motedeck.windows_diagnostics",
    "motedeck.settings_ui", "motedeck.key_mapping",
)
HELPER_LAUNCHER = "src/hid_helper_launcher.py"


def helper_source_files(root: Path) -> list[Path]:
    """Return the helper launcher plus its import closure as sorted paths."""
    sources = module_sources(root)
    seeds = list(HELPER_SEEDS)
    files = {
        sources[name]
        for name in import_closure(root, seeds, excludes=HELPER_EXCLUDES)
        if name in sources
    }
    launcher = root / HELPER_LAUNCHER
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    files.add(launcher)
    return sorted(files)
