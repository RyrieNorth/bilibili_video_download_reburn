"""日志与调试设施。

控制台走 RichHandler，以便与进度条共存而不打乱画面；
文件 handler 沿用紧凑格式且恒为 DEBUG 级别，独立于控制台级别。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from rich.logging import RichHandler

from .ui import get_console

LOGGER_NAME = "bilidl"
_configured = False


class CompactFormatter(logging.Formatter):
    """写入文件时使用的紧凑单行格式（无颜色）。

    (bilidl pid=1234) 02-18 02:09:30 aria2:62 INFO   : Message...
    """

    def __init__(self, component_name: str = "bilidl"):
        super().__init__()
        self.component_name = component_name

    def format(self, record: logging.LogRecord) -> str:
        prefix = f"({self.component_name} pid={os.getpid()})"
        timestamp = self.formatTime(record, "%m-%d %H:%M:%S")
        location = f"{record.module}:{record.lineno}"
        output = (
            f"{prefix} {timestamp} {location} {record.levelname}"
            f"{record.getMessage()}"
        )

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            output += "\n" + record.exc_text
        if record.stack_info:
            output += "\n" + self.formatStack(record.stack_info)
        return output


def debug_enabled(flag: bool = False) -> bool:
    """--debug 或环境变量 BILIDL_DEBUG=1 任一生效即为调试模式。"""
    if flag:
        return True
    return os.environ.get("BILIDL_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def setup_logging(
    debug: bool = False,
    log_file: str | Path | None = None,
    quiet: bool = False,
) -> logging.Logger:
    """初始化根 logger。重复调用只生效一次，便于测试与嵌套调用。"""
    global _configured

    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)  # 由各 handler 自行过滤
    logger.propagate = False

    console_level = logging.DEBUG if debug else (logging.WARNING if quiet else logging.INFO)
    console_handler = RichHandler(
        console=get_console(),
        show_time=True,
        show_path=debug,
        omit_repeated_times=False,
        rich_tracebacks=True,
        markup=False,
        log_time_format="[%m-%d %H:%M:%S]",
    )
    console_handler.setLevel(console_level)
    console_handler._log_render.level_width = 6
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    if log_file:
        path = Path(log_file).expanduser()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
        except OSError as exc:
            logger.warning(f"无法写入日志文件 {path}: {exc}")
        else:
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(CompactFormatter())
            logger.addHandler(file_handler)
            logger.debug(f"日志文件已启用: {path}")

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """取得子 logger；未初始化时也能安全使用。"""
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def install_traceback(debug: bool) -> None:
    """调试模式下安装 rich traceback，附带局部变量便于定位。"""
    if not debug:
        return
    from rich.traceback import install

    install(console=get_console(), show_locals=True, width=None)


