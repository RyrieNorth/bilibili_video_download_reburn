from __future__ import annotations

from pathlib import Path

from .api.api import BiliClient
from .auth.auth import Authenticator
from .config import CONFIG_FILE, load_settings
from .tools.downloader import Downloader, DownloadOptions
from .utils import ui
from .utils.log import setup_logging

__all__ = ["download", "main"]


def download(
    video_id: str,
    *,
    quality: str | int | None = None,
    pages: str | None = None,
    only_video: bool = False,
    only_audio: bool = False,
    output_dir: str | Path | None = None,
    overwrite: bool = False,
    keep_temp: bool = False,
    dry_run: bool = False,
    concurrency: int | None = None,
    interactive: bool = False,
    allow_login: bool = True,
    force_login: bool = False,
    config: str | Path | None = None,
    debug: bool = False,
    log_file: str | Path | None = None,
    show_summary: bool = False,
) -> list[ui.TaskOutcome]:
    """下载一个稿件（BV / av / ss / ep 均可），返回每个分P 的结果。

    关键字参数与命令行选项一一对应。未显式指定时的行为：

    - ``pages=None``   → 全部分P，不询问
    - ``quality=None`` → 可用的最高清晰度，不询问
    - 只有 ``interactive=True`` 才会在两者缺省时弹出选择表（需要真实终端）

    注意：单个分P 失败**不会**抛异常，只在返回值里记 ``state="failed"``，
    以便多P 场景下其余任务继续。整体性错误（稿件不存在、外部工具缺失、
    aria2 起不来等）以 :class:`~bilidl.errors.BiliDLError` 抛出。

    ``dry_run=True`` 只打印预览表并返回空列表，不产生任何 TaskOutcome。
    """
    setup_logging(debug=debug, log_file=str(log_file) if log_file else None)

    settings = load_settings(Path(config) if config else CONFIG_FILE)
    login = Authenticator(settings).resolve(
        allow_login=allow_login, force_login=force_login
    )

    options = DownloadOptions(
        quality=quality,
        pages=pages,
        only_video=only_video,
        only_audio=only_audio,
        output_dir=str(output_dir) if output_dir is not None else None,
        overwrite=overwrite,
        keep_temp=keep_temp,
        dry_run=dry_run,
        interactive=interactive,
        concurrency=concurrency,
    )

    with BiliClient(settings, login.cookies) as client:
        downloader = Downloader(settings, client, login, options, debug=debug)
        outcomes = downloader.run(video_id)

    if show_summary and not dry_run:
        ui.show_summary(outcomes, downloader.output_dir)

    return outcomes


# 兼容旧写法 main(video_id)
main = download
