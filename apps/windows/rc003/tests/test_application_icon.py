import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ovb_rc003 import qt_settings_app


_RC003_ROOT = Path(__file__).resolve().parents[1]
_ICON_DIR = _RC003_ROOT / "src" / "ovb_rc003" / "assets" / "icons"
_GENERATOR = _RC003_ROOT / "build" / "generate-app-icon.py"


class ApplicationIconTests(unittest.TestCase):
    def test_application_icon_is_a_valid_square_png(self):
        from PySide6.QtGui import QImage

        image = QImage(str(_ICON_DIR / "remote-mic.png"))
        self.assertFalse(image.isNull())
        self.assertEqual(image.width(), image.height())

    def test_application_and_installer_pngs_match_the_brand_svg(self):
        import runpy

        generator = runpy.run_path(str(_GENERATOR))
        svg_path = _RC003_ROOT / "src" / "ovb_rc003" / "qml" / "assets" / "brand-mark.svg"
        for path, size in (
            (_ICON_DIR / "remote-mic.png", 1024),
            (_RC003_ROOT / "installer" / "wizard-small.png", 55),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    path.read_bytes(), generator["render_brand_png"](svg_path, size)
                )

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
