import hashlib
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovb_rc003 import qt_settings_app, resources


_RC003_ROOT = Path(__file__).resolve().parents[1]
_ICON_DIR = _RC003_ROOT / "src" / "ovb_rc003" / "assets" / "icons"
_GENERATOR = _RC003_ROOT / "build" / "generate-app-icon.py"
_APP_ICON_SHA256 = "62e057c9e830c83d627b2c5f9550af9b5d5506245982754703cfce915302212a"
_TRAY_ICON_SHA256 = "8d3242f8e9a2cc26f8d7916306b736a82a8ff60c279abc2aeeea267aec449e95"


class ApplicationIconTests(unittest.TestCase):
    def test_application_icon_is_a_valid_square_png(self):
        from PySide6.QtGui import QImage

        image = QImage(str(_ICON_DIR / "remote-mic.png"))
        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), image.height())

    def test_application_png_matches_the_approved_high_resolution_source(self):
        path = _ICON_DIR / "remote-mic.png"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), _APP_ICON_SHA256)

    def test_tray_png_matches_the_approved_source(self):
        path = _ICON_DIR / "remote-mic-tray.png"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), _TRAY_ICON_SHA256)

    def test_wizard_png_is_scaled_from_the_application_png(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        source = QImage(str(_ICON_DIR / "remote-mic.png"))
        expected = source.scaled(55, 55, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        actual = QImage(str(_RC003_ROOT / "installer" / "wizard-small.png"))
        self.assertEqual((actual.width(), actual.height()), (55, 55))
        self.assertEqual(
            actual.convertToFormat(QImage.Format_ARGB32),
            expected.convertToFormat(QImage.Format_ARGB32),
        )

    def test_tray_ico_is_derived_from_the_independent_png(self):
        import runpy
        from PySide6.QtGui import QImage

        generator = runpy.run_path(str(_GENERATOR))
        content = (_ICON_DIR / "remote-mic-tray.ico").read_bytes()
        self.assertEqual(content, generator["build_ico"](_ICON_DIR / "remote-mic-tray.png"))
        for index, size in enumerate(generator["ICON_SIZES"]):
            entry = struct.unpack_from("<BBBBHHII", content, 6 + 16 * index)
            image = QImage.fromData(content[entry[7]:entry[7] + entry[6]], "PNG")
            self.assertEqual((image.width(), image.height()), (size, size))

    def test_icon_generator_is_idempotent_and_preserves_png_sources(self):
        application_png = _ICON_DIR / "remote-mic.png"
        tray_png = _ICON_DIR / "remote-mic-tray.png"
        before = application_png.read_bytes(), tray_png.read_bytes()
        result = subprocess.run(
            [sys.executable, str(_GENERATOR)],
            cwd=_RC003_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = application_png.read_bytes(), tray_png.read_bytes()
        self.assertEqual(after, before)
        first_generated = (
            (_ICON_DIR / "remote-mic.ico").read_bytes(),
            (_ICON_DIR / "remote-mic-tray.ico").read_bytes(),
            (_RC003_ROOT / "installer" / "wizard-small.png").read_bytes(),
        )
        result = subprocess.run(
            [sys.executable, str(_GENERATOR)],
            cwd=_RC003_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            first_generated,
            (
                (_ICON_DIR / "remote-mic.ico").read_bytes(),
                (_ICON_DIR / "remote-mic-tray.ico").read_bytes(),
                (_RC003_ROOT / "installer" / "wizard-small.png").read_bytes(),
            ),
        )

    def test_find_tray_icon_keeps_stopped_state_and_uses_separate_running_source(self):
        self.assertEqual(resources.find_tray_icon("off").name, "remote-mic-stopped.png")
        self.assertEqual(resources.find_tray_icon("waiting").name, "remote-mic-tray.png")
        self.assertEqual(resources.find_tray_icon("connected").name, "remote-mic-tray.png")
        self.assertEqual(resources.find_app_icon("connected").name, "remote-mic.png")

    def test_navigation_icon_uses_theme_specific_svg_resources(self):
        import xml.etree.ElementTree as ET

        qml_dir = _RC003_ROOT / "src" / "ovb_rc003" / "qml"
        light = ET.parse(qml_dir / "assets" / "brand-mark.svg").getroot()
        dark = ET.parse(qml_dir / "assets" / "brand-mark-dark.svg").getroot()
        self.assertEqual(len(list(light.iter())), len(list(dark.iter())) + 1)
        light_shapes = {
            node.attrib["id"]: node.attrib for node in light.iter()
            if "id" in node.attrib and node.attrib["id"] != "tile"
        }
        dark_shapes = {
            node.attrib["id"]: node.attrib for node in dark.iter()
            if "id" in node.attrib
        }
        self.assertNotIn("tile", dark_shapes)
        self.assertEqual(dark_shapes, light_shapes)
        main = (qml_dir / "main.qml").read_text(encoding="utf-8")
        logo = main.split('id: appLogo', 1)[1].split('Column {', 1)[0]
        self.assertIn(
            'window.tokens.darkMode\n'
            '                    ? "assets/brand-mark-dark.svg" : "assets/brand-mark.svg"',
            logo,
        )
        self.assertIn('MoteDeckWordmark {\n                    objectName: "titleWordmark"', main)

    def test_qt_icon_is_applied_to_the_application_and_native_window(self):
        calls = []

        class FakeIcon:
            def __init__(self, path):
                self.path = path

        class FakeApplication:
            def setWindowIcon(self, icon):
                calls.append(("application", icon.path))

        class FakeWindow:
            def setIcon(self, icon):
                calls.append(("window", icon.path))

        icon_path = _ICON_DIR / "remote-mic.png"
        qt_settings_app._apply_application_icon(
            FakeApplication(), FakeWindow(), FakeIcon, icon_path
        )

        self.assertEqual(
            calls,
            [
                ("application", str(icon_path)),
                ("window", str(icon_path)),
            ],
        )

    def test_windows_ico_is_generated_from_the_shared_png(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            generated = Path(tmpdir) / "remote-mic.ico"
            result = subprocess.run(
                [
                    sys.executable,
                    str(_GENERATOR),
                    "--source",
                    str(_ICON_DIR / "remote-mic.png"),
                    "--output",
                    str(generated),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                generated.read_bytes(),
                (_ICON_DIR / "remote-mic.ico").read_bytes(),
            )

            content = generated.read_bytes()
            _reserved, image_type, image_count = struct.unpack_from("<HHH", content)
            self.assertEqual(image_type, 1)
            self.assertEqual(image_count, 9)

    def test_builds_regenerate_the_shared_windows_icon(self):
        local_build = (_RC003_ROOT / "build" / "build-candidate.ps1").read_text(
            encoding="utf-8"
        )
        ci = (
            _RC003_ROOT.parents[2]
            / ".github"
            / "workflows"
            / "windows-rc003-ci.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("generate-app-icon.py", local_build)
        self.assertIn("python build/generate-app-icon.py", ci)

    def test_development_shortcut_uses_the_shared_ico_directly(self):
        script = (_RC003_ROOT / "build" / "install-dev-shortcut.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("src\\ovb_rc003\\assets\\icons\\remote-mic.ico", script)
        self.assertNotIn("dist\\RemoteMicRC003\\RemoteMicRC003.exe", script)


if __name__ == "__main__":
    unittest.main()
