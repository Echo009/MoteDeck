"""Generate shared Windows and installer icons from the brand SVG."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _render_png(source: QImage, size: int) -> bytes:
    image = source.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )

    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.WriteOnly) or not image.save(buffer, "PNG"):
        raise RuntimeError(f"could not render {size}x{size} application icon")
    buffer.close()
    return bytes(payload)


def render_brand_png(svg_path: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"invalid SVG icon: {svg_path}")
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    payload = QByteArray()
    buffer = QBuffer(payload)
    if not buffer.open(QIODevice.WriteOnly) or not image.save(buffer, "PNG"):
        raise RuntimeError(f"could not render {size}x{size} application icon")
    buffer.close()
    return bytes(payload)


def write_if_changed(path: Path, content: bytes) -> None:
    if path.is_file() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def build_ico(png_path: Path) -> bytes:
    source = QImage(str(png_path))
    if source.isNull():
        raise ValueError(f"invalid PNG icon: {png_path}")

    images = [(size, _render_png(source, size)) for size in ICON_SIZES]
    offset = 6 + 16 * len(images)
    entries = []
    payloads = []
    for size, payload in images:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.append(payload)
        offset += len(payload)
    return b"".join((struct.pack("<HHH", 0, 1, len(images)), *entries, *payloads))


def main() -> int:
    rc003_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    icon_dir = rc003_root / "src" / "ovb_rc003" / "assets" / "icons"
    if args.source is None and args.output is None:
        png_path = icon_dir / "remote-mic.png"
        ico_path = icon_dir / "remote-mic.ico"
        wizard_path = rc003_root / "installer" / "wizard-small.png"
        svg_path = rc003_root / "src" / "ovb_rc003" / "qml" / "assets" / "brand-mark.svg"
        write_if_changed(png_path, render_brand_png(svg_path, 1024))
        write_if_changed(wizard_path, render_brand_png(svg_path, 55))
    else:
        png_path = args.source or icon_dir / "remote-mic.png"
        ico_path = args.output or icon_dir / "remote-mic.ico"

    write_if_changed(ico_path.resolve(), build_ico(png_path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
