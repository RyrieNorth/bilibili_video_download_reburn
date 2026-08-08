"""数据模型与纯逻辑选择器。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ApiError, ArgumentError

# 编码偏好：默认优先 H.264，兼容性最好；其次 HEVC，最后 AV1
DEFAULT_CODEC_PREFERENCE = ("avc", "hev", "av01")

# 音质 id 映射
AUDIO_LABELS = {
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30250: "杜比全景声",
    30251: "Hi-Res 无损",
}

# 音质优先级
AUDIO_QUALITY_RANK = {
    30216: 1,  # 64K
    30232: 2,  # 132K
    30280: 3,  # 192K
    30250: 4,  # 杜比全景声
    30251: 5,  # Hi-Res 无损
}


@dataclass(frozen=True)
class Page:
    """一个分P（或番剧的一集）。"""

    cid: int
    index: int  # 1 起的序号
    title: str
    duration: int = 0  # 秒
    bvid: str | None = None

    @property
    def display_title(self) -> str:
        return self.title or f"P{self.index}"


@dataclass(frozen=True)
class Stream:
    """单路音频或视频流。"""

    url: str
    stream_id: int
    kind: str  # "video" | "audio"
    codec: str = ""
    bandwidth: int = 0
    label: str = ""
    width: int = 0
    height: int = 0
    backup_urls: tuple[str, ...] = ()

    @property
    def urls(self) -> list[str]:
        """主链接 + 备用链接，aria2 会依次尝试。"""
        return [self.url, *self.backup_urls]

    def estimated_size(self, duration: int) -> int:
        """按码率与时长估算体积（字节）。"""
        if not self.bandwidth or not duration:
            return 0
        return int(self.bandwidth / 8 * duration)


@dataclass(frozen=True)
class QualityOption:
    """playurl 返回的可选清晰度。"""

    quality_id: int
    label: str
    available: bool = True
    needs_vip: bool = False

    @property
    def note(self) -> str:
        if not self.available:
            return "需登录/大会员"
        if self.needs_vip:
            return "大会员"
        return "可下载"


@dataclass
class Task:
    """待处理的下载单元：视频流 + 音频流合并为一个 mp4。"""

    page: Page
    video: Stream
    audio: Stream
    output: Path
    video_tmp: Path
    audio_tmp: Path
    quality_label: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.page.display_title

    @property
    def estimated_size(self) -> int:
        duration = self.page.duration
        return self.video.estimated_size(duration) + self.audio.estimated_size(duration)


_RANGE_PATTERN = re.compile(r"^(\d+)\s*-\s*(\d+)$")


def parse_page_selection(expr: str | None, total: int) -> list[int]:
    """解析形如 "1-3,5,8" 的选择表达式，返回 1 起的升序去重序号列表。

    空串或 "all" 表示全选。越界或格式非法抛 ArgumentError。
    """
    if total <= 0:
        return []

    if expr is None:
        return list(range(1, total + 1))

    text = expr.strip().lower()
    if text in {"", "all", "*", "a"}:
        return list(range(1, total + 1))

    selected: set[int] = set()
    for chunk in text.replace("，", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue

        if match := _RANGE_PATTERN.match(chunk):
            start, end = int(match.group(1)), int(match.group(2))
            if start > end:
                start, end = end, start
            _check_bounds(start, total, expr)
            _check_bounds(end, total, expr)
            selected.update(range(start, end + 1))
        elif chunk.isdigit():
            value = int(chunk)
            _check_bounds(value, total, expr)
            selected.add(value)
        else:
            raise ArgumentError(
                f"输入无效 '{chunk}'",
                hint='示例：1、1-3、1-3,5,8，或 all 表示全部。',
            )

    if not selected:
        raise ArgumentError(f"分P选择 '{expr}' 没有匹配到任何一项")

    return sorted(selected)


def _check_bounds(value: int, total: int, expr: str) -> None:
    if not 1 <= value <= total:
        raise ArgumentError(
            f"分P序号 {value} 超出范围（共 {total} 个）",
            hint=f"请将 '{expr}' 调整 1 到 {total} 之间的序号。",
        )


def _codec_rank(codec: str, preference: tuple[str, ...]) -> int:
    lowered = (codec or "").lower()
    for rank, prefix in enumerate(preference):
        if lowered.startswith(prefix):
            return rank
    return len(preference)


def select_video_stream(
    streams: list[Stream],
    requested_quality: int | None = None,
    codec_preference: tuple[str, ...] = DEFAULT_CODEC_PREFERENCE,
) -> tuple[Stream, bool]:
    """获取视频流。检查视频流, 是否发生了降级。

    requested_quality 为 None 表示取最高档。若指定档位不存在，
    则取不超过它的最高档；若全都高于它，则取最低档。
    """
    if not streams:
        raise ApiError(
            "接口未返回任何可用视频流",
            hint="该稿件可能有版权限制，或需要登录后才能获取播放地址。",
        )

    def best_of(candidates: list[Stream]) -> Stream:
        # 同一档位可能有多种编码，按编码偏好再按码率取优
        return min(
            candidates,
            key=lambda s: (_codec_rank(s.codec, codec_preference), -s.bandwidth),
        )

    if requested_quality is None:
        top = max(s.stream_id for s in streams)
        return best_of([s for s in streams if s.stream_id == top]), False

    exact = [s for s in streams if s.stream_id == requested_quality]
    if exact:
        return best_of(exact), False

    lower = [s for s in streams if s.stream_id < requested_quality]
    if lower:
        fallback_id = max(s.stream_id for s in lower)
        return best_of([s for s in lower if s.stream_id == fallback_id]), True

    lowest_id = min(s.stream_id for s in streams)
    return best_of([s for s in streams if s.stream_id == lowest_id]), True


def select_audio_stream(streams: list[Stream]) -> Stream:
    """取可用音轨中音质最好的一路（无损 > 杜比 > 192K > 132K > 64K）。

    未知 id 排在所有已知档之前保守处理（视为最低优先），以码率作为次要依据。
    """
    if not streams:
        raise ApiError(
            "接口未返回任何可用音频流",
            hint="该稿件可能是无声视频，或播放地址已失效，请重试。",
        )
    return max(
        streams,
        key=lambda s: (AUDIO_QUALITY_RANK.get(s.stream_id, 0), s.bandwidth),
    )
