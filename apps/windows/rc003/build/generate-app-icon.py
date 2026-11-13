"""Generate Windows and installer icons from the supplied product PNG."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter


ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _render_png(source: QImage, size: int) -> bytes:
    scaled = source.scaled(
        size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
    )
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
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

    icon_dir = rc003_root / "src" / "motedeck" / "assets" / "icons"
    png_path = args.source or icon_dir / "remote-mic.png"
    ico_path = args.output or icon_dir / "remote-mic.ico"
    write_if_changed(ico_path.resolve(), build_ico(png_path.resolve()))

    if args.source is None and args.output is None:
        tray_png_path = icon_dir / "remote-mic-tray.png"
        tray_ico_path = icon_dir / "remote-mic-tray.ico"
        wizard_path = rc003_root / "installer" / "wizard-small.png"
        write_if_changed(tray_ico_path.resolve(), build_ico(tray_png_path.resolve()))
        write_if_changed(wizard_path, _render_png(QImage(str(png_path)), 55))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
