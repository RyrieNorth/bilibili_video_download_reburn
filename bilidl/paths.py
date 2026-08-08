"""路径工具：文件名净化、外部工具发现、输出目录管理。"""

from __future__ import annotations

import os
import platform
import re
import shutil
import stat
from pathlib import Path

from .errors import ToolNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"

# Windows 保留设备名，即便带扩展名也不可用
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')
# 不含 \t \n \v \f \r：这几个交给下面的空白折叠，直接删除会把词粘到一起
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_WHITESPACE_RUN = re.compile(r"\s+")

# 为 "_audio.m4s" 之类的后缀预留空间，避免超出文件系统单段上限
MAX_FILENAME_BYTES = 150


def sanitize_filename(name: str, fallback: str = "untitled") -> str:
    """把任意标题净化成跨平台安全的单个文件名片段（不含扩展名）。

    处理非法字符、控制字符、尾部点与空格、Windows 保留名，并按字节截断。
    """
    if not name:
        return fallback

    cleaned = _CONTROL_CHARS.sub("", name)
    cleaned = _ILLEGAL_CHARS.sub("_", cleaned)
    cleaned = _WHITESPACE_RUN.sub(" ", cleaned).strip()
    # Windows 会自动去掉结尾的点和空格，提前处理避免出现名字不一致
    cleaned = cleaned.rstrip(". ")

    if not cleaned:
        return fallback

    if cleaned.split(".")[0].upper() in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    cleaned = _truncate_bytes(cleaned, MAX_FILENAME_BYTES)
    cleaned = cleaned.rstrip(". ")

    return cleaned or fallback


def _truncate_bytes(text: str, limit: int, encoding: str = "utf-8") -> str:
    """按编码后的字节数截断，且不切坏多字节字符。"""
    encoded = text.encode(encoding)
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode(encoding, errors="ignore")


def unique_path(path: Path) -> Path:
    """若目标已存在，则追加 (1)、(2) … 直到得到未占用的路径。"""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"无法为 {path} 找到可用的文件名")


def ensure_dir(path: Path) -> Path:
    """创建目录（含父级）并返回绝对路径。"""
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _add_execute_permission(path: Path) -> None:
    """类 Unix 平台上为自带二进制补执行权限。"""
    if platform.system() == "Windows":
        return
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        # 权限补不上不代表一定不能执行，交由后续实际调用报错
        pass


def find_tool(name: str) -> Path:
    """定位外部工具：优先使用 tools/ 下自带的，其次回落到 PATH。

    name 传不带扩展名的基础名，如 "aria2c" / "ffmpeg"。
    """
    filename = f"{name}.exe" if os.name == "nt" else name
    bundled = TOOLS_DIR / filename

    if bundled.is_file():
        _add_execute_permission(bundled)
        return bundled.resolve()

    from_path = shutil.which(name)
    if from_path:
        return Path(from_path).resolve()

    raise ToolNotFoundError(
        f"找不到可执行文件 {name}",
        hint=(
            f"请把 {filename} 放到 {TOOLS_DIR} 目录下，"
            f"或将其所在目录加入系统 PATH中。"
        ),
    )
