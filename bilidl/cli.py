"""命令行入口：参数解析、装配依赖、统一异常收口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .utils import ui
from .api.api import BiliClient
from .auth.auth import Authenticator
from .config import CONFIG_FILE, load_settings
from .tools.downloader import Downloader, DownloadOptions
from .errors import BiliDLError
from .utils.log import debug_enabled, get_logger, install_traceback, setup_logging

EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bilidl",
        description="Bilibili 视频下载工具（支持单P/多P/番剧，自动合并为 MP4）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:"
            "  bilidl BV1xx411c7mD"
            "  bilidl BV1xx411c7mD --quality best --pages 1-3\n"
            "  bilidl ss12345 --quality 80 --output D:/anime\n"
            "  bilidl BV1xx411c7mD --dry-run --debug\n"
        ),
    )
    parser.add_argument(
        "video_id",
        help="BV 号、av 号、番剧 ss/ep 号，或直接粘贴视频页面链接",
    )

    selection = parser.add_argument_group("选择")
    selection.add_argument(
        "--quality",
        metavar="Q",
        help="清晰度：best、worst 或具体 qn（如 80=1080P）。省略则交互选择",
    )
    selection.add_argument(
        "--pages",
        metavar="EXPR",
        help='分P选择，如 "1-3,5" 或 "all"。省略则交互选择',
    )

    output = parser.add_argument_group("输出")
    output.add_argument("-o", "--output", metavar="DIR", help="输出目录，默认 ./video")
    output.add_argument(
        "--overwrite", action="store_true", help="目标 mp4 已存在时也重新下载"
    )
    output.add_argument(
        "--keep-temp", action="store_true", help="合并成功后保留 .m4s 临时文件"
    )
    output.add_argument(
        "--concurrency",
        type=int,
        metavar="N",
        help="同时下载的视频数量，默认取配置中的 download.concurrent_downloads",
    )

    auth = parser.add_argument_group("登录")
    auth.add_argument(
        "--no-login",
        action="store_true",
        help="不弹出扫码，以游客身份继续（清晰度会受限）",
    )
    auth.add_argument(
        "--relogin", action="store_true", help="忽略本地 Cookies，强制重新扫码登录"
    )

    debug = parser.add_argument_group("调试")
    debug.add_argument(
        "--dry-run",
        action="store_true",
        help="只解析并展示待下载计划，不实际下载",
    )
    debug.add_argument(
        "--debug",
        action="store_true",
        help="输出 DEBUG 日志与详细堆栈（等价于 BILIDL_DEBUG=1）",
    )
    debug.add_argument("--log-file", metavar="PATH", help="把 DEBUG 级日志写入文件")
    debug.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    debug.add_argument(
        "--config",
        metavar="PATH",
        default=str(CONFIG_FILE),
        help=f"配置文件路径，默认 {CONFIG_FILE}",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    debug = debug_enabled(args.debug)
    ui.configure_console(no_color=args.no_color)
    setup_logging(debug=debug, log_file=args.log_file)
    install_traceback(debug)
    logger = get_logger("cli")

    if debug:
        logger.debug(f"命令行参数: {vars(args)}")

    try:
        return _run(args, debug)
    except KeyboardInterrupt:
        ui.get_console().print("\n已被用户中断。", style="yellow")
        return EXIT_INTERRUPTED
    except BiliDLError as exc:
        if debug:
            raise
        ui.show_error(exc)
        logger.debug("详细堆栈:", exc_info=True)
        return exc.exit_code
    except Exception as exc:
        if debug:
            raise
        ui.show_error(exc)
        ui.get_console().print(
            "可加 --debug 查看完整堆栈，或用 --log-file 保存日志后反馈。", style="dim"
        )
        logger.debug("未预期的异常:", exc_info=True)
        return 1


def _run(args: argparse.Namespace, debug: bool) -> int:
    settings = load_settings(Path(args.config))

    authenticator = Authenticator(settings)
    login = authenticator.resolve(
        allow_login=not args.no_login, force_login=args.relogin
    )

    options = DownloadOptions(
        quality=args.quality,
        pages=args.pages,
        output_dir=args.output,
        overwrite=args.overwrite,
        keep_temp=args.keep_temp,
        dry_run=args.dry_run,
        # 未指定 --quality/--pages 且处于真实终端时才进入交互
        interactive=sys.stdin.isatty(),
        concurrency=args.concurrency,
    )

    with BiliClient(settings, login.cookies) as client:
        downloader = Downloader(settings, client, login, options, debug=debug)
        outcomes = downloader.run(args.video_id)

    if args.dry_run:
        return 0

    ui.show_summary(outcomes, downloader.output_dir)

    if not outcomes:
        return 0
    if any(o.state == "failed" for o in outcomes):
        return 1
    return 0


def run() -> None:
    """console_scripts 入口。"""
    sys.exit(main())


if __name__ == "__main__":
    run()
