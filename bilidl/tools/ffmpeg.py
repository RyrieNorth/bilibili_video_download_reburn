"""ffmpeg 封装：把分离的音视频流复用为 mp4。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import MuxError
from ..utils.log import get_logger
from ..paths import find_tool

logger = get_logger("ffmpeg")

# 单个文件的合并超时（秒）。-c copy 只是复用容器，正常远快于此
DEFAULT_TIMEOUT = 1800

# 轮询进度文件的间隔
POLL_INTERVAL = 0.2

# ffmpeg 在“解析参数阶段”就失败的特征：这类错误与片源无关，而是构建不匹配
_OPTION_ERROR_MARKERS = (
    "Protocol not found",
    "Error parsing global options",
    "Unrecognized option",
    "Error splitting the argument list",
    "Option not found",
)

ProgressCallback = Callable[[float], None]


@dataclass
class MuxResult:
    output: Path
    duration_ms: int = 0


class FFmpegMuxer:
    """调用 ffmpeg 做流复用（-c copy，不重编码）。"""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        self.executable = find_tool("ffmpeg")
        self.timeout = timeout

    def build_command(
        self,
        video: Path,
        audio: Path,
        output: Path,
        progress_path: Path | None = None,
    ) -> list[str]:
        command = [
            str(self.executable),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
        ]
        if progress_path is not None:
            # 必须写普通文件：自带的 ffmpeg 是 --disable-everything 精简构建，
            # 只编译了 file 协议，-progress pipe:1 会在解析全局参数时直接报
            # "Protocol not found" 并退出，导致每次合并必败
            command += ["-progress", str(progress_path), "-nostats"]
        command += [
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            # 便于边下边播 / 网页拖动
            "-movflags",
            "+faststart",
            str(output),
        ]
        return command

    def build_single_command(
        self,
        source: Path,
        output: Path,
        kind: str,
        progress_path: Path | None = None,
    ) -> list[str]:
        """--only-video / --only-audio：只复制单一路流，不重编码。

        kind 为 "video" 或 "audio"，决定取哪一路 map 以及是否需要 faststart。
        """
        command = [
            str(self.executable),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
        ]
        if progress_path is not None:
            command += ["-progress", str(progress_path), "-nostats"]
        stream_map = "0:v:0" if kind == "video" else "0:a:0"
        command += ["-y", "-i", str(source), "-map", stream_map, "-c", "copy"]
        if kind == "video":
            # 音频容器（.m4a）不需要 faststart
            command += ["-movflags", "+faststart"]
        # 这个精简构建只编译了 mp4 muxer，没有 ipod/m4a，靠扩展名猜 muxer
        # 对 .m4a 输出会报 "Unable to choose an output format"，必须显式指定
        command += ["-f", "mp4", str(output)]
        return command

    def mux(
        self,
        video: Path,
        audio: Path,
        output: Path,
        duration: int = 0,
        on_progress: ProgressCallback | None = None,
    ) -> MuxResult:
        """合并音视频。失败抛 MuxError，并附带 ffmpeg 的错误输出尾部。

        duration 为视频秒数，用于把 out_time_ms 换算成百分比；为 0 时不报进度。
        """
        self._check_input(video, "视频")
        self._check_input(audio, "音频")
        return self._run(
            lambda progress_path: self.build_command(video, audio, output, progress_path),
            output,
            duration,
            on_progress,
        )

    def remux(
        self,
        source: Path,
        output: Path,
        kind: str,
        duration: int = 0,
        on_progress: ProgressCallback | None = None,
    ) -> MuxResult:
        """--only-video / --only-audio 场景下把单一路流复制进最终容器。

        kind 为 "video" 或 "audio"；不做二次编码，只是换容器（沿用 mux 的
        进度/错误处理逻辑）。
        """
        label = "视频" if kind == "video" else "音频"
        self._check_input(source, label)
        return self._run(
            lambda progress_path: self.build_single_command(source, output, kind, progress_path),
            output,
            duration,
            on_progress,
        )

    def _run(
        self,
        command_factory: Callable[[Path], list[str]],
        output: Path,
        duration: int,
        on_progress: ProgressCallback | None,
    ) -> MuxResult:
        """跑一次 ffmpeg 子进程并等待完成，mux/remux 共用同一套进度轮询与报错。"""
        output.parent.mkdir(parents=True, exist_ok=True)

        # 进度与 stderr 均落临时文件：既绕开精简构建缺失的 pipe 协议，
        # 也不存在管道写满后双方互等的风险
        with tempfile.TemporaryDirectory(prefix="bilidl-mux-") as tmpdir:
            progress_path = Path(tmpdir) / "progress.txt"
            stderr_path = Path(tmpdir) / "stderr.txt"
            progress_path.touch()

            command = command_factory(progress_path)
            logger.debug(f"运行 ffmpeg: {' '.join(command)}")

            try:
                with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr_file:
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=stderr_file,
                        stdin=subprocess.DEVNULL,
                        shell=False,
                        creationflags=_no_window_flag(),
                    )
                    last_time_ms = self._watch(
                        process, progress_path, output, duration, on_progress
                    )
            except OSError as exc:
                raise MuxError(
                    f"无法启动 ffmpeg: {exc}",
                    hint=f"请确认 {self.executable} 可执行。",
                ) from exc

            returncode = process.returncode
            stderr = _read_text(stderr_path)

        if returncode != 0:
            tail = _tail(stderr, 20)
            raise MuxError(
                f"ffmpeg 合并失败（返回码 {_describe_returncode(returncode)}）: {output.name}",
                stderr_tail=tail,
                hint=_hint_for_failure(tail),
            )

        if not output.exists() or output.stat().st_size == 0:
            raise MuxError(
                f"ffmpeg 声称成功但输出文件无效: {output}",
                stderr_tail=_tail(stderr, 20),
            )

        logger.debug(f"处理完成: {output}")
        return MuxResult(output=output, duration_ms=last_time_ms // 1000)

    def _watch(
        self,
        process: subprocess.Popen,
        progress_path: Path,
        output: Path,
        duration: int,
        on_progress: ProgressCallback | None,
    ) -> int:
        """边等进程退出边轮询进度文件，返回最后一次 out_time_ms。"""
        reader = _ProgressFile(progress_path)
        deadline = time.monotonic() + self.timeout

        try:
            while True:
                try:
                    process.wait(timeout=POLL_INTERVAL)
                except subprocess.TimeoutExpired:
                    reader.pump(duration, on_progress)
                    if time.monotonic() > deadline:
                        _kill(process)
                        raise MuxError(
                            f"ffmpeg 合并超时（超过 {self.timeout:.0f}s）: {output.name}",
                            hint="音视频流可能异常，可加 --keep-temp 后手动排查 .m4s 文件。",
                        ) from None
                    continue
                break
        except KeyboardInterrupt:
            _kill(process)
            raise

        # 进程已退出，补读尾部剩余的进度
        return reader.pump(duration, on_progress)

    @staticmethod
    def _check_input(path: Path, label: str) -> None:
        if not path.exists():
            raise MuxError(
                f"{label}文件不存在: {path}",
                hint="下载可能未完成，请重新运行。",
            )
        if path.stat().st_size == 0:
            raise MuxError(
                f"{label}文件为空: {path}",
                hint="下载结果异常，请加 --overwrite 重新下载。",
            )


class _ProgressFile:
    """增量读取 ffmpeg 写出的 -progress 文件。

    文件是 "key=value" 的追加式文本，按字节偏移推进，并缓存可能读到的半行。
    """

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        self._partial = ""
        self.last_time_ms = 0

    def pump(self, duration: int, on_progress: ProgressCallback | None) -> int:
        try:
            with self.path.open("rb") as handle:
                handle.seek(self._offset)
                chunk = handle.read()
                self._offset = handle.tell()
        except OSError:
            # 进度文件读不到不影响合并本身
            return self.last_time_ms

        if not chunk:
            return self.last_time_ms

        text = self._partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._partial = lines.pop()  # 末尾可能是尚未写完的一行
        for line in lines:
            self._consume(line.strip(), duration, on_progress)
        return self.last_time_ms

    def _consume(
        self, line: str, duration: int, on_progress: ProgressCallback | None
    ) -> None:
        key, _, value = line.partition("=")
        # 注意 out_time_ms 实际单位是微秒（ffmpeg 历史命名问题）
        if key == "out_time_ms" and value.isdigit():
            self.last_time_ms = int(value)
            if on_progress and duration > 0:
                percent = min(self.last_time_ms / (duration * 1_000_000) * 100, 100)
                on_progress(percent)
        elif key == "progress" and value == "end" and on_progress:
            on_progress(100.0)


def _hint_for_failure(stderr_tail: str) -> str:
    """根据 ffmpeg 的真实报错给出建议，避免一律归因于“流损坏”。"""
    if any(marker in stderr_tail for marker in _OPTION_ERROR_MARKERS):
        return (
            "ffmpeg 在解析参数阶段就失败了，与下载的文件无关："
            "当前 ffmpeg 构建缺少所需功能，请换用完整版 ffmpeg。"
        )
    return (
        "音视频流可能损坏或不完整。已保留 .m4s 临时文件，可用 --overwrite 重新下载。"
    )


def _describe_returncode(code: int) -> str:
    """Windows 的异常退出码是很大的无符号数，附上十六进制才有可读性。"""
    if code < 0 or code > 0xFFFF:
        return f"{code} (0x{code & 0xFFFFFFFF:08X})"
    return str(code)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _kill(process: subprocess.Popen) -> None:
    """确保不留孤儿 ffmpeg 进程。"""
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _tail(text: str | None, lines: int) -> str:
    if not text:
        return ""
    return "\n".join(text.strip().splitlines()[-lines:])


def _no_window_flag() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0
