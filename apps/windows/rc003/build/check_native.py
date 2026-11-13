"""Verify native-stage coverage/origins and run the single complete test pass.

Build-time only. Receipts/logs live in ignored build caches, never in a release.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from native_inventory import (module_sources, NAVIGATION_MODULES, MAIN_BOOTSTRAP,
                              LEGACY_MODULES, PYTHON_ONLY_MODULES)

ROOT = Path(__file__).resolve().parents[1]


def verify_stage(stage: Path, *, require_full: bool = True) -> dict:
    stage = stage.resolve()
    receipt = json.loads((stage / "native-build.json").read_text(encoding="utf-8"))
    sources = module_sources(ROOT)
    records = receipt["modules"]
    if receipt["python"] != sys.version:
        raise RuntimeError("native stage belongs to a different Python interpreter")
    if require_full and (receipt["scope"] != "full"
                         or set(records) != set(sources) - set(PYTHON_ONLY_MODULES)):
        raise RuntimeError("native inventory does not match current business modules")
    if require_full and (stage / "src/motedeck/__main__.py").read_text(encoding="utf-8") != MAIN_BOOTSTRAP:
        raise RuntimeError("native entrypoint bootstrap is missing or changed")
    if not require_full:
        if receipt["scope"] != "legacy" or set(records) != set(LEGACY_MODULES):
            raise RuntimeError("invalid legacy comparison inventory")
        for name, source in sources.items():
            if name not in records:
                staged = stage / source.relative_to(ROOT)
                if not staged.is_file() or staged.read_bytes() != source.read_bytes():
                    raise RuntimeError(f"legacy comparison source changed: {name}")
    for name, record in records.items():
        if name not in sources:
            raise RuntimeError(f"unknown compiled module: {name}")
        if hashlib.sha256(sources[name].read_bytes()).hexdigest() != record["source_sha256"]:
            raise RuntimeError(f"native source changed: {name}")
        directory = stage / "scripts" if name in NAVIGATION_MODULES else stage / "src" / "motedeck"
        expected = [directory / (name.split(".")[-1] + suffix)
                    for suffix in importlib.machinery.EXTENSION_SUFFIXES]
        binary = stage / record["output"]
        if binary not in expected or not binary.is_file():
            raise RuntimeError(f"invalid native output path: {name}")
        if hashlib.sha256(binary.read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError(f"native binary changed: {name}")
        stem = name.split(".")[-1]
        if (directory / f"{stem}.py").exists() or (directory / f"{stem}.pyc").exists():
            raise RuntimeError(f"native output retains Python business code: {name}")
        if list((directory / "__pycache__").glob(f"{stem}.*.pyc")):
            raise RuntimeError(f"native output retains cached business code: {name}")
    if require_full:
        # 未编译模块必须以当前源码的 .py 形式留在 stage 里，PyInstaller 才会
        # 把它们打成 .pyc 进包；缺失或过期等于悄悄丢掉 Frida HID 通道。
        for name in set(sources) - set(records):
            staged = stage / "src" / Path(*name.split(".")).with_suffix(".py")
            if not staged.is_file() or staged.read_bytes() != sources[name].read_bytes():
                raise RuntimeError(f"bytecode module missing from native stage: {name}")
    return receipt


def verify_artifact(directory: Path, receipt: dict) -> None:
    """Inspect both EXE archives as well as the external native modules."""
    from PyInstaller.archive.readers import CArchiveReader
    from importlib.util import module_from_spec, spec_from_file_location

    executables = list(directory.glob("*.exe"))
    if len(executables) != 1:
        raise RuntimeError("expected exactly one main executable")
    identity_spec = spec_from_file_location(
        "_native_product_identity", ROOT / "src/motedeck/product_identity.py")
    identity = module_from_spec(identity_spec)
    identity_spec.loader.exec_module(identity)
    runtime = directory / identity.WINDOWS_RUNTIME_DIRECTORY_NAME
    helper = runtime / "MoteDeckHidHelper.exe"
    for name, record in receipt["modules"].items():
        parent = runtime / ("element_navigation" if name in NAVIGATION_MODULES else "motedeck")
        matches = [parent / (name.split(".")[-1] + suffix)
                   for suffix in importlib.machinery.EXTENSION_SUFFIXES
                   if (parent / (name.split(".")[-1] + suffix)).is_file()]
        if len(matches) != 1 or hashlib.sha256(matches[0].read_bytes()).hexdigest() != record["sha256"]:
            raise RuntimeError(f"frozen native module missing or changed: {name}")
    for parent in (runtime / "motedeck", runtime / "element_navigation"):
        for file in parent.rglob("*"):
            if file.suffix in (".py", ".pyc", ".pyo", ".c", ".cpp", ".h", ".pdb"):
                raise RuntimeError(f"business source/debug artifact leaked: {file}")
    frozen_bytecode = set()
    for executable in (*executables, helper):
        archive = CArchiveReader(str(executable))
        for entry, value in archive.toc.items():
            if value[-1] == "z":
                pyz = archive.open_embedded_archive(entry)
                forbidden = set(pyz.toc) & set(receipt["modules"])
                if forbidden:
                    raise RuntimeError(f"Python business bytecode leaked in {executable.name}: {sorted(forbidden)}")
                if executable in executables:
                    frozen_bytecode |= set(pyz.toc)
        if executable == helper:
            names = [entry.replace("\\", "/") for entry in archive.toc]
            for stem in ("hid_elevation_windows",):
                if not any(n.startswith("motedeck/" + stem) and n.endswith(".pyd") for n in names):
                    raise RuntimeError(f"helper lacks native permission module: {stem}")
            if any(n.startswith(("PySide6/", "numpy/", "winrt/")) for n in names):
                raise RuntimeError("privileged helper unexpectedly contains UI/audio/BLE dependencies")
            for entry in archive.toc:
                normalized = entry.replace("\\", "/")
                if normalized.startswith("motedeck/") and normalized.endswith(".pyd"):
                    name = "motedeck." + Path(normalized).name.split(".")[0]
                    if (name not in receipt["modules"] or
                            hashlib.sha256(archive.extract(entry)).hexdigest()
                            != receipt["modules"][name]["sha256"]):
                        raise RuntimeError(f"helper native module changed: {name}")
    missing_bytecode = set(PYTHON_ONLY_MODULES) - frozen_bytecode
    if missing_bytecode:
        raise RuntimeError(f"frozen bytecode modules missing: {sorted(missing_bytecode)}")
    print(f"verified frozen native modules and both EXE archives: {len(receipt['modules'])}", flush=True)


def verify_imports(stage: Path, receipt: dict) -> None:
    sys.path.insert(0, str(stage / "src"))
    sys.path.insert(0, str(stage / "scripts"))
    for name, record in receipt["modules"].items():
        module = importlib.import_module(name)
        if Path(module.__file__).resolve() != (stage / record["output"]).resolve():
            raise RuntimeError(f"module escaped native stage: {name}: {module.__file__}")
    print(f"verified native import origins: {len(receipt['modules'])}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--test-module", action="append", default=[])
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve()
    receipt = verify_stage(stage)
    if args.artifact:
        verify_artifact(args.artifact.resolve(), receipt)
        return 0
    os.environ["MOTEDECK_NATIVE_STAGE"] = str(stage)
    os.environ["PYTHONPATH"] = str(stage / "src")
    os.environ["MOTEDECK_DISABLE_LIVE_INPUT"] = "1"
    os.environ["RC003_ALLOW_LIVE_INPUT_TESTS"] = "0"
    verify_imports(stage, receipt)
    if not args.tests:
        return 0
    sys.path.insert(0, str(ROOT))
    with tempfile.TemporaryDirectory(prefix="remote-mic-native-tests-") as temporary:
        os.environ["LOCALAPPDATA"] = temporary
        suite = (unittest.defaultTestLoader.loadTestsFromNames(args.test_module)
                 if args.test_module else
                 unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT)))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
