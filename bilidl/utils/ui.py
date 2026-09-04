"""基于 rich 的交互界面：清晰度/分P选择、并行进度条、结果汇总。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from rich.box import SIMPLE_HEAD
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from ..errors import ApiError, ArgumentError
from .models import Page, QualityOption, Stream, Task, parse_page_selection

_console: Console | None = None


def get_console() -> Console:
    """全局唯一 Console，保证日志与进度条共用同一个输出通道。"""
    global _console
    if _console is None:
        _console = Console()
    return _console


def configure_console(no_color: bool = False) -> Console:
    """在 CLI 启动时按参数重建 Console（如禁用颜色）。"""
    global _console
    _console = Console(no_color=no_color, highlight=not no_color, soft_wrap=False)
    return _console


def format_size(num_bytes: float) -> str:
    if num_bytes <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            precision = 0 if unit == "B" else 1
            return f"{num_bytes:.{precision}f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "-"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def truncate(text: str, width: int = 34) -> str:
    """按显示宽度截断，避免中文标题把进度条挤出屏幕。"""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def show_header(title: str, subtitle: str = "") -> None:
    console = get_console()
    body = Text(title, style="bold")
    if subtitle:
        body.append(f"\n{subtitle}", style="dim")
    console.print(Panel(body, border_style="cyan", expand=False))


def select_quality(
    options: Sequence[QualityOption],
    preset: str | int | None = None,
    interactive: bool = True,
) -> int:
    """展示清晰度表并返回选定的 qn。

    preset 支持 "best" / "worst" / 具体 qn 数字，给定时不再询问。
    """
    ordered = sorted(options, key=lambda o: o.quality_id, reverse=True)
    if not ordered:
        raise ApiError(
            "接口未返回任何可选清晰度",
            hint="该稿件可能有版权限制，或需要登录后才能获取播放地址。",
        )

    if preset is not None:
        return _resolve_quality_preset(ordered, preset)

    if not interactive:
        return ordered[0].quality_id

    console = get_console()
    table = Table(box=SIMPLE_HEAD, title="可选清晰度", title_style="bold")
    table.add_column("序号", justify="right", style="cyan", width=4)
    table.add_column("清晰度")
    table.add_column("qn", justify="right", style="dim", width=5)
    table.add_column("状态", style="dim")

    for index, option in enumerate(ordered, start=1):
        style = "" if option.available else "dim strike"
        table.add_row(
            str(index),
            Text(option.label, style=style),
            str(option.quality_id),
            option.note,
        )

    console.print(table)
    choice = Prompt.ask(
        "请选择清晰度",
        choices=[str(i) for i in range(1, len(ordered) + 1)],
        default="1",
        show_choices=False,
        console=console,
    )
    return ordered[int(choice) - 1].quality_id


def _resolve_quality_preset(
    ordered: Sequence[QualityOption], preset: str | int
) -> int:
    text = str(preset).strip().lower()
    if text in {"best", "max", "highest"}:
        return ordered[0].quality_id
    if text in {"worst", "min", "lowest"}:
        return ordered[-1].quality_id
    if text.isdigit():
        return int(text)
    raise ArgumentError(
        f"无法识别的清晰度参数: {preset}",
        hint="可用值：best、worst，或具体的 qn 数字（如 80 表示 1080P）。",
    )


def select_pages(
    pages: Sequence[Page],
    expr: str | None = None,
    interactive: bool = True,
    label: str = "分P",
) -> list[Page]:
    """展示分P/剧集表并返回选中的项。expr 给定时不再询问。"""
    # 先校验显式给定的表达式：单P 时也要对 --pages 1-5 这类越界输入报错，而不是默默忽略
    if expr is not None:
        indexes = parse_page_selection(expr, len(pages))
        return [pages[i - 1] for i in indexes]

    if len(pages) <= 1:
        return list(pages)

    console = get_console()
    table = Table(box=SIMPLE_HEAD, title=f"共 {len(pages)} 个{label}", title_style="bold")
    table.add_column("序号", justify="right", style="cyan", width=4)
    table.add_column("标题")
    table.add_column("时长", justify="right", style="dim", width=8)

    for index, page in enumerate(pages, start=1):
        table.add_row(str(index), page.display_title, format_duration(page.duration))

    console.print(table)

    if not interactive:
        return list(pages)

    while True:
        raw = Prompt.ask(
            f"请选择要下载的{label}（如 1-3,5；回车为全部）",
            default="all",
            console=console,
        )
        try:
            indexes = parse_page_selection(raw, len(pages))
        except ArgumentError as exc:
            # 交互输入出错不必终止整个流程，重新询问即可
            console.print(f"[yellow]{exc.message}[/yellow]")
            continue
        return [pages[i - 1] for i in indexes]


def show_plan(tasks: Sequence[Task], output_dir: Path) -> None:
    """--dry-run 时展示解析结果，不做任何下载。"""
    console = get_console()
    table = Table(
        box=SIMPLE_HEAD,
        title="待下载任务（dry-run，未实际下载）",
        title_style="bold",
    )
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("标题")
    table.add_column("清晰度", width=8)
    table.add_column("编码", style="dim", width=12)
    table.add_column("音轨", style="dim", width=8)
    table.add_column("预估体积", justify="right", width=9)
    table.add_column("输出文件")

    total = 0
    for index, task in enumerate(tasks, start=1):
        total += task.estimated_size
        table.add_row(
            str(index),
            truncate(task.name, 30),
            task.quality_label or "-",
            task.video.codec if task.video else "-",
            task.audio.label if task.audio else "-",
            format_size(task.estimated_size),
            task.output.name,
        )

    console.print(table)
    console.print(
        f"共 {len(tasks)} 个任务，预估总体积 {format_size(total)}，输出目录: {output_dir}",
        style="dim",
    )


class SpeedColumn(ProgressColumn):
    """直接展示 aria2 上报的真实速度，而非 rich 自行估算的值。"""

    def render(self, task) -> Text:
        speed = task.fields.get("speed") or 0
        if not speed:
            return Text("-", style="dim")
        return Text(f"{format_size(speed)}/s", style="green")


class SizeColumn(ProgressColumn):
    """已下载 / 总大小。总大小未知时只显示已下载量。"""

    def render(self, task) -> Text:
        completed = format_size(task.completed)
        if not task.total:
            return Text(completed, style="dim")
        return Text(f"{completed}/{format_size(task.total)}", style="dim")


@dataclass
class ProgressHandle:
    """一个进度行的句柄。"""

    task_id: TaskID
    progress: Progress

    def update(self, completed: int, total: int = 0, speed: int = 0) -> None:
        fields: dict = {"speed": speed}
        if total:
            fields["total"] = total
        self.progress.update(self.task_id, completed=completed, **fields)

    def set_description(self, text: str) -> None:
        self.progress.update(self.task_id, description=text)

    def finish(self, note: str = "") -> None:
        task = self.progress.tasks[self.task_id]
        total = task.total or task.completed or 1
        self.progress.update(
            self.task_id, completed=total, total=total, speed=0
        )
        if note:
            self.set_description(note)

    def fail(self, note: str) -> None:
        self.progress.update(self.task_id, description=note, speed=0)


class TransferProgress:
    """包装 rich.Progress：每个文件一行，下载与合并共用同一个面板。"""

    def __init__(self, transient: bool = False):
        self.console = get_console()
        self.progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold]{task.description}", justify="left"),
            BarColumn(bar_width=26),
            TextColumn("{task.percentage:>5.1f}%"),
            SizeColumn(),
            SpeedColumn(),
            TimeRemainingColumn(compact=True),
            console=self.console,
            transient=transient,
            refresh_per_second=8,
        )

    def __enter__(self) -> TransferProgress:
        self.progress.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.progress.stop()

    def add(self, description: str, total: int = 0) -> ProgressHandle:
        task_id = self.progress.add_task(
            truncate(description), total=total or None, speed=0
        )
        return ProgressHandle(task_id=task_id, progress=self.progress)

    def log(self, message: str, style: str = "") -> None:
        """在进度面板上方输出一行，不会打乱进度条。"""
        self.progress.console.print(message, style=style)


@dataclass
class TaskOutcome:
    name: str
    state: str  # "success" | "skipped" | "failed"
    detail: str = ""
    output: Path | None = None


STATE_STYLES = {
    "success": ("完成", "green"),
    "skipped": ("跳过", "yellow"),
    "failed": ("失败", "red"),
}


def show_summary(outcomes: Sequence[TaskOutcome], output_dir: Path) -> None:
    """打印成功/跳过/失败的汇总表。"""
    console = get_console()
    if not outcomes:
        console.print("没有任何任务被执行。", style="yellow")
        return

    table = Table(box=SIMPLE_HEAD, title="下载结果", title_style="bold")
    table.add_column("状态", width=6)
    table.add_column("标题")
    table.add_column("说明", style="dim")

    counts = {"success": 0, "skipped": 0, "failed": 0}
    for outcome in outcomes:
        label, style = STATE_STYLES.get(outcome.state, (outcome.state, ""))
        counts[outcome.state] = counts.get(outcome.state, 0) + 1
        table.add_row(
            Text(label, style=style), truncate(outcome.name, 40), outcome.detail
        )

    console.print(table)

    parts = [f"成功 {counts.get('success', 0)}"]
    if counts.get("skipped"):
        parts.append(f"跳过 {counts['skipped']}")
    if counts.get("failed"):
        parts.append(f"失败 {counts['failed']}")
    console.print(
        f"{'，'.join(parts)}。文件位于: {output_dir}",
        style="bold green" if not counts.get("failed") else "bold yellow",
    )


def show_error(exc: BaseException) -> None:
    """统一的错误展示：主信息 + 可操作建议 + 子进程输出尾部。"""
    console = get_console()
    console.print(f"错误: {exc}", style="bold red")

    hint = getattr(exc, "hint", None)
    if hint:
        console.print(f"建议: {hint}", style="yellow")

    tail = getattr(exc, "stderr_tail", None)
    if tail:
        console.print(
            Panel(tail, title="子进程输出", border_style="red", expand=False)
        )

