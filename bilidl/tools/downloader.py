"""编排层：解析目标 -> 构建任务 -> aria2 下载 -> ffmpeg 合并。

关键设计：
- 下载并发交给 aria2 内部调度，本层只提交 GID 并用单个轮询循环刷新进度；
- 每对音视频一下载完就立刻投给合并线程池，与剩余下载重叠，而不是全部下完再串行合并；
- 番剧只请求一次 season 接口，清晰度只询问一次并复用到所有剧集。
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..utils import ui
from ..api.api import BiliClient, normalize_video_id
from .aria2 import Aria2Daemon, Aria2Rpc, build_download_options, describe_error
from ..auth.auth import LoginState
from ..config import Settings
from ..errors import BiliDLError, DownloadError, MuxError
from .ffmpeg import FFmpegMuxer
from ..utils.log import get_logger
from ..utils.models import Page, Stream, Task, select_audio_stream, select_video_stream
from ..paths import ensure_dir, sanitize_filename
from ..utils.ui import TaskOutcome

logger = get_logger("downloader")


@dataclass
class DownloadOptions:
    """一次运行的全部行为开关，由 cli.py 组装。"""

    quality: str | int | None = None
    pages: str | None = None
    output_dir: str | None = None
    overwrite: bool = False
    keep_temp: bool = False
    dry_run: bool = False
    only_video: bool = False
    only_audio: bool = False
    interactive: bool = True
    concurrency: int | None = None


@dataclass
class _Pending:
    task: Task
    video_gid: str | None
    audio_gid: str | None
    handle: ui.ProgressHandle
    done_video: bool = False
    done_audio: bool = False
    submitted_to_mux: bool = False

    @property
    def ready(self) -> bool:
        return self.done_video and self.done_audio


class Downloader:
    def __init__(
        self,
        settings: Settings,
        client: BiliClient,
        login: LoginState,
        options: DownloadOptions,
        debug: bool = False,
    ):
        self.settings = settings
        self.client = client
        self.login = login
        self.options = options
        self.debug = debug
        self.output_dir = ensure_dir(settings.resolve_output_dir(options.output_dir))
        self.outcomes: list[TaskOutcome] = []

    def run(self, raw_id: str) -> list[TaskOutcome]:
        id_type, video_id = normalize_video_id(raw_id)
        logger.debug(f"识别输入 {raw_id!r} -> type={id_type} id={video_id}")

        if id_type in {"ss", "ep"}:
            title, pages = self.client.get_season_episodes(id_type, video_id)
            label = "剧集"
            fallback_bvid = None
        else:
            title, pages = self.client.get_pages(id_type, video_id)
            label = "分P"
            fallback_bvid = pages[0].bvid if pages else video_id

        ui.show_header(title, f"共 {len(pages)} 个{label}")
        selected = ui.select_pages(
            pages, self.options.pages, self.options.interactive, label
        )
        if not selected:
            ui.get_console().print("未选择任何项目，已退出。", style="yellow")
            return []

        tasks = self._build_tasks(title, selected, fallback_bvid)
        if not tasks:
            return self.outcomes

        if self.options.dry_run:
            ui.show_plan(tasks, self.output_dir)
            return self.outcomes

        self._execute(tasks)
        return self.outcomes

    # ------------------------------------------------------------------
    # 任务构建
    # ------------------------------------------------------------------

    def _build_tasks(
        self, album_title: str, pages: Sequence[Page], fallback_bvid: str | None
    ) -> list[Task]:
        """拉取播放地址、确定清晰度、组装 Task 列表。

        清晰度只询问一次（用第一个分P的可选列表），随后复用到全部分P。
        """
        first = pages[0]
        first_bvid = first.bvid or fallback_bvid
        if not first_bvid:
            raise BiliDLError(
                "无法确定该内容的 BV 号",
                hint="番剧剧集数据可能缺少 bvid，请改用具体的 BV 号下载。",
            )

        probe = self.client.get_playurl(first_bvid, first.cid)
        quality_options = self.client.get_quality_options(probe)
        # --only-audio 时音轨与 qn 无关，不必询问，静静取可用最高档即可
        quality = ui.select_quality(
            quality_options,
            self.options.quality,
            self.options.interactive and not self.options.only_audio,
        )
        logger.debug(f"目标清晰度 qn={quality}")

        playurls = self.client.get_playurls_parallel(
            first_bvid, list(pages), quality, workers=4
        )
        # 首个分P已经用探测结果拿过一次，避免重复请求
        if isinstance(playurls.get(first.cid), Exception) or first.cid not in playurls:
            playurls[first.cid] = probe

        multi = len(pages) > 1
        tasks: list[Task] = []
        for page in pages:
            payload = playurls.get(page.cid)
            if isinstance(payload, Exception):
                self._record_failure(page.display_title, payload)
                continue
            if not isinstance(payload, dict):
                self._record_failure(
                    page.display_title, BiliDLError("未取得播放地址")
                )
                continue

            try:
                task = self._make_task(album_title, page, payload, quality, multi)
            except BiliDLError as exc:
                self._record_failure(page.display_title, exc)
                continue
            tasks.append(task)

        return tasks

    def _make_task(
        self,
        album_title: str,
        page: Page,
        playurl: dict,
        quality: int,
        multi: bool,
    ) -> Task:
        videos, audios = self.client.parse_streams(playurl)

        video: Stream | None = None
        audio: Stream | None = None
        if not self.options.only_audio:
            video, downgraded = select_video_stream(videos, quality)
            if downgraded:
                logger.warning(
                    f"{page.display_title}: 目标清晰度不可用，已降级为 {video.label} "
                    f"(qn={video.stream_id})"
                )
        if not self.options.only_video:
            audio = select_audio_stream(audios)

        # 多P时用 "稿件标题 - P1 分P标题" 便于归档；单P直接用标题
        if multi:
            raw_name = f"{album_title} - P{page.index} {page.display_title}"
        else:
            raw_name = page.display_title or album_title
        stem = sanitize_filename(raw_name, fallback=f"cid_{page.cid}")

        # 时长优先取播放接口返回值，番剧的 pages.duration 可能为 0
        duration = page.duration or int((playurl.get("dash") or {}).get("duration", 0) or 0)
        if duration != page.duration:
            page = Page(
                cid=page.cid,
                index=page.index,
                title=page.title,
                duration=duration,
                bvid=page.bvid,
            )

        # --only-audio 输出为 .m4a，其余情况（完整下载 / --only-video）都是 .mp4
        if self.options.only_audio:
            output = self.output_dir / f"{stem}.m4a"
            quality_label = audio.label
        else:
            output = self.output_dir / f"{stem}.mp4"
            quality_label = video.label

        return Task(
            page=page,
            video=video,
            audio=audio,
            output=output,
            video_tmp=self.output_dir / f"{stem}.video.m4s" if video is not None else None,
            audio_tmp=self.output_dir / f"{stem}.audio.m4s" if audio is not None else None,
            quality_label=quality_label,
        )

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def _execute(self, tasks: list[Task]) -> None:
        runnable = [t for t in tasks if not self._skip_existing(t)]
        if not runnable:
            return

        concurrency = self.options.concurrency or self.settings.download.concurrent_downloads
        muxer = FFmpegMuxer()

        daemon = Aria2Daemon(self.settings.aria2, self.output_dir, debug=self.debug)
        rpc = daemon.start()

        try:
            with ui.TransferProgress() as progress, ThreadPoolExecutor(
                max_workers=max(1, self.settings.download.mux_workers),
                thread_name_prefix="mux",
            ) as mux_pool:
                self._pump(rpc, runnable, progress, mux_pool, muxer, concurrency)
        except KeyboardInterrupt:
            ui.get_console().print("\n已中断，正在清理 aria2c ...", style="yellow")
            raise
        finally:
            daemon.stop()

    def _skip_existing(self, task: Task) -> bool:
        """目标 mp4 已存在且未指定 --overwrite 时跳过。"""
        if task.output.exists() and not self.options.overwrite:
            logger.info(f"已存在，跳过: {task.output.name}")
            self.outcomes.append(
                TaskOutcome(
                    name=task.name,
                    state="skipped",
                    detail="目标文件已存在（使用 --overwrite 强制重下）",
                    output=task.output,
                )
            )
            return True
        return False

    def _pump(
        self,
        rpc: Aria2Rpc,
        tasks: list[Task],
        progress: ui.TransferProgress,
        mux_pool: ThreadPoolExecutor,
        muxer: FFmpegMuxer,
        concurrency: int,
    ) -> None:
        """提交下载 -> 轮询进度 -> 完成即投递合并。

        单个任务失败不中断整体流程，只记入汇总并继续处理其余任务。
        """
        cookie_header = self.login.cookie_header
        queue = list(tasks)
        mux_futures: dict[Future, _Pending] = {}
        active: list[_Pending] = []

        while queue or active or mux_futures:
            # 补足并发窗口
            while queue and len(active) < max(1, concurrency):
                task = queue.pop(0)
                try:
                    item = self._submit(rpc, task, progress, cookie_header)
                except BiliDLError as exc:
                    self._record_failure(task.name, exc)
                    continue
                active.append(item)

            if active:
                for item, error in self._refresh(rpc, active):
                    # 另一路流可能还在跑，一并停掉以节省带宽
                    for gid in (item.video_gid, item.audio_gid):
                        if gid is not None:
                            rpc.remove(gid)
                    item.handle.fail(f"失败 {ui.truncate(item.task.name, 26)}")
                    self._record_failure(item.task.name, error)
                    logger.error(f"{item.task.name}: {error}")
                    active.remove(item)

            # 下载完成的任务转入合并
            for item in list(active):
                if not item.ready or item.submitted_to_mux:
                    continue
                item.submitted_to_mux = True
                item.handle.set_description(f"合并 {ui.truncate(item.task.name, 28)}")
                future = mux_pool.submit(self._mux_one, muxer, item)
                mux_futures[future] = item
                active.remove(item)

            # 回收已完成的合并
            for future in [f for f in mux_futures if f.done()]:
                item = mux_futures.pop(future)
                self._collect_mux(future, item)

            if active or queue or mux_futures:
                time.sleep(self.settings.aria2.poll_interval)

    def _submit(
        self,
        rpc: Aria2Rpc,
        task: Task,
        progress: ui.TransferProgress,
        cookie_header: str,
    ) -> _Pending:
        """把一对（或单路）音视频提交给 aria2，返回待跟踪对象。"""
        if self.options.overwrite:
            # 重下时清掉可能残留的半成品，避免 --continue 接到旧数据上
            for temp in (task.video_tmp, task.audio_tmp):
                if temp is not None:
                    temp.unlink(missing_ok=True)

        video_gid: str | None = None
        audio_gid: str | None = None
        if task.video is not None:
            video_gid = rpc.add_uri(
                task.video.urls,
                build_download_options(
                    task.video_tmp.name,
                    self.settings.referer,
                    self.settings.user_agent,
                    cookie_header,
                ),
            )
        if task.audio is not None:
            audio_gid = rpc.add_uri(
                task.audio.urls,
                build_download_options(
                    task.audio_tmp.name,
                    self.settings.referer,
                    self.settings.user_agent,
                    cookie_header,
                ),
            )
        logger.debug(
            f"{task.name}: 提交下载 video_gid={video_gid} audio_gid={audio_gid}"
        )

        handle = progress.add(task.name, total=task.estimated_size)
        return _Pending(
            task=task,
            video_gid=video_gid,
            audio_gid=audio_gid,
            handle=handle,
            # 未提交的那路直接视为已完成，不用等它的状态
            done_video=task.video is None,
            done_audio=task.audio is None,
        )

    def _refresh(
        self, rpc: Aria2Rpc, active: list[_Pending]
    ) -> list[tuple[_Pending, DownloadError]]:
        """一次 multicall 拉全部 GID 状态并刷新进度条。

        返回本轮新出现的失败项，由调用方决定如何处理。
        """
        gids = [
            gid
            for item in active
            for gid in (item.video_gid, item.audio_gid)
            if gid is not None
        ]
        statuses = rpc.tell_status_batch(gids)
        failures: list[tuple[_Pending, DownloadError]] = []

        for item in active:
            video = statuses.get(item.video_gid) if item.video_gid else None
            audio = statuses.get(item.audio_gid) if item.audio_gid else None

            completed = 0
            total = 0
            speed = 0
            for status in (video, audio):
                if status is None:
                    continue
                completed += status.completed
                total += status.total
                speed += status.speed

            item.handle.update(completed=completed, total=total, speed=speed)

            failure: DownloadError | None = None
            for kind, status in (("视频", video), ("音频", audio)):
                if status is not None and status.failed:
                    base = describe_error(status)
                    failure = DownloadError(
                        f"{kind}流{base.message}",
                        filename=item.task.name,
                        error_code=base.error_code,
                        hint=base.hint,
                    )
                    break

            if failure is not None:
                failures.append((item, failure))
                continue

            if video is not None and video.status == "complete":
                item.done_video = True
            if audio is not None and audio.status == "complete":
                item.done_audio = True

        return failures

    def _mux_one(self, muxer: FFmpegMuxer, item: _Pending) -> Path:
        """在合并线程里执行 ffmpeg，并按需清理临时文件。

        只下载了单路流（--only-video / --only-audio）时改走 remux，
        不尝试与存在不存在的另一路合并。
        """
        task = item.task
        if task.video is not None and task.audio is not None:
            result = muxer.mux(
                task.video_tmp,
                task.audio_tmp,
                task.output,
                duration=task.page.duration,
            )
        elif task.video is not None:
            result = muxer.remux(
                task.video_tmp, task.output, kind="video", duration=task.page.duration
            )
        else:
            result = muxer.remux(
                task.audio_tmp, task.output, kind="audio", duration=task.page.duration
            )

        if not self.options.keep_temp:
            for temp in (task.video_tmp, task.audio_tmp):
                if temp is None:
                    continue
                try:
                    temp.unlink(missing_ok=True)
                except OSError as exc:
                    logger.debug(f"临时文件删除失败 {temp}: {exc}")

        return result.output

    def _collect_mux(self, future: Future, item: _Pending) -> None:
        try:
            output = future.result()
        except MuxError as exc:
            item.handle.fail(f"合并失败 {ui.truncate(item.task.name, 24)}")
            self._record_failure(item.task.name, exc)
            logger.error(f"{item.task.name}: {exc}")
            if exc.stderr_tail:
                logger.error(f"ffmpeg 输出:\n{exc.stderr_tail}")
            return
        except Exception as exc:
            item.handle.fail(f"失败 {ui.truncate(item.task.name, 26)}")
            self._record_failure(item.task.name, exc)
            logger.exception(f"{item.task.name}: 合并时发生未预期错误")
            return

        item.handle.finish(f"完成 {ui.truncate(item.task.name, 26)}")
        self.outcomes.append(
            TaskOutcome(
                name=item.task.name,
                state="success",
                detail=item.task.quality_label,
                output=output,
            )
        )

    def _record_failure(self, name: str, exc: BaseException) -> None:
        hint = getattr(exc, "hint", None)
        detail = str(exc)
        if hint:
            detail = f"{detail}（{hint}）"
        self.outcomes.append(TaskOutcome(name=name, state="failed", detail=detail))
