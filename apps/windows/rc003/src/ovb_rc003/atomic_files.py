r"""原子写文件的统一入口，顺带处理被系统重定向的目录。

Windows 上 ``%LOCALAPPDATA%`` 可能被整体挪到别的盘（例如 ``D:\WpSystem\...``），
程序拿到的路径只是一层“门牌号”。在门牌号目录里建临时文件、再 ``os.replace``
过去时，系统会按真实位置判定成“跨盘搬运”并报 WinError 17。这里统一先把
目录解析成真实路径再落盘；万一仍然失败，就退化成“先备份、再就地覆盖”，
保证内容一定写得进去。
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional, Union

# Win32 ERROR_NOT_SAME_DEVICE：源和目标在系统看来属于不同的卷。
_ERROR_NOT_SAME_DEVICE = 17

PrepareCallback = Callable[[Path], None]


def resolve_real_path(path: Union[Path, str]) -> Path:
    """把被 junction / 符号链接重定向的路径还原成真实物理路径。

    文件还不存在时逐级向上找最近的已存在目录，再把剩余部分拼回去。
    """

    current = Path(path)
    try:
        if current.exists():
            return Path(os.path.realpath(current))
    except OSError:
        pass
    parent = current.parent
    if parent == current:
        return current
    resolved_parent = resolve_real_path(parent)
    if resolved_parent == parent:
        return current
    return resolved_parent / current.name


def is_cross_device_error(error: OSError) -> bool:
    if getattr(error, "winerror", None) == _ERROR_NOT_SAME_DEVICE:
        return True
    return error.errno == errno.EXDEV


def write_bytes_atomic(
    path: Union[Path, str],
    content: bytes,
    *,
    prepare: Optional[PrepareCallback] = None,
) -> None:
    """把 ``content`` 一次写进 ``path``，不会暴露写了一半的文件。

    ``prepare`` 会在临时文件落盘后、正式替换前调用，用来给文件补权限；
    走“就地覆盖”兜底时也会对目标文件再调一次。
    """

    destination = resolve_real_path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if prepare is not None:
            prepare(temporary)
        replace_existing(temporary, destination, prepare=prepare)
    except BaseException:
        unlink_quietly(temporary)
        raise


def write_text_atomic(
    path: Union[Path, str],
    text: str,
    *,
    encoding: str = "utf-8",
    prepare: Optional[PrepareCallback] = None,
) -> None:
    write_bytes_atomic(path, text.encode(encoding), prepare=prepare)


def replace_existing(
    temporary: Union[Path, str],
    destination: Union[Path, str],
    *,
    prepare: Optional[PrepareCallback] = None,
) -> None:
    """把已经写好的临时文件换成正式文件，跨盘时自动兜底。"""

    source = Path(temporary)
    target = resolve_real_path(destination)
    try:
        os.replace(source, target)
        return
    except OSError as error:
        if not is_cross_device_error(error):
            raise
    _overwrite_in_place(source, target)
    if prepare is not None:
        prepare(target)
    unlink_quietly(source)


def _overwrite_in_place(source: Path, destination: Path) -> None:
    """系统不让“换名字”时，改成“先备份、再直接覆盖、最后删备份”。"""

    backup = destination.with_name(f".{destination.name}.bak")
    had_original = destination.exists()
    if had_original:
        shutil.copyfile(destination, backup)
    try:
        with open(source, "rb") as reader, open(destination, "wb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        if had_original:
            try:
                shutil.copyfile(backup, destination)
            except OSError:
                pass
        raise
    finally:
        if had_original:
            unlink_quietly(backup)


def unlink_quietly(path: Union[Path, str]) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
