"""config.json 的解析与校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
COOKIES_FILE = PROJECT_ROOT / "cookie.json"

DEFAULT_URLS = {
    "get_qrcode": "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
    "check_qrcode_scan": "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
    "play_api": "https://api.bilibili.com/x/player/playurl",
    "convert_cid": "https://api.bilibili.com/x/player/pagelist",
    "login_url": "https://api.bilibili.com/x/web-interface/nav",
    "video_info": "https://api.bilibili.com/x/web-interface/view",
    "get_anime": "https://api.bilibili.com/pgc/view/web/season",
}

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "referer": "https://www.bilibili.com",
}


@dataclass
class NetworkConfig:
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    retries: int = 3
    backoff_factor: float = 0.5

    @property
    def timeout(self) -> tuple[float, float]:
        return (self.connect_timeout, self.read_timeout)


@dataclass
class Aria2Config:
    split: int = 8
    max_connection_per_server: int = 2
    rpc_port: int = 0  # 0 表示自动挑选空闲端口
    startup_timeout: float = 10.0
    poll_interval: float = 0.4
    extra_args: list[str] = field(default_factory=list)


@dataclass
class DownloadConfig:
    output_dir: str = "video"
    concurrent_downloads: int = 3
    mux_workers: int = 2


@dataclass
class Settings:
    urls: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_URLS))
    headers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HEADERS))
    network: NetworkConfig = field(default_factory=NetworkConfig)
    aria2: Aria2Config = field(default_factory=Aria2Config)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    source_path: Path | None = None

    @property
    def referer(self) -> str:
        return self.headers.get("referer", DEFAULT_HEADERS["referer"])

    @property
    def user_agent(self) -> str:
        return self.headers.get("user-agent", DEFAULT_HEADERS["user-agent"])

    def url(self, key: str) -> str:
        try:
            return self.urls[key]
        except KeyError as exc:
            raise ConfigError(
                f"配置缺少接口地址 url.{key}",
                hint=f"请在 {self.source_path or CONFIG_FILE} 的 url 段补上该字段。",
            ) from exc

    def resolve_output_dir(self, override: str | None = None) -> Path:
        """确定输出目录。相对路径基于当前工作目录，不是安装路径：

        命令行工具的相对路径约定应该相对于用户运行命令时的 cwd，
        否则 --output ./out 会跟着安装位置跑，与用户预期不符。
        """
        raw = override or self.download.output_dir
        path = Path(raw).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path)


def _as_section(data: dict[str, Any], key: str) -> dict[str, Any]:
    """取出一个字典段；类型不对则抛 ConfigError，缺失则返回空字典。"""
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"配置段 '{key}' 应为对象，实际为 {type(value).__name__}")
    return value


def _as_int(section: dict[str, Any], key: str, default: int) -> int:
    """兼容旧配置里把数字写成字符串的写法（如 "split": "8"）。"""
    raw = section.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置项 '{key}' 应为整数，实际为 {raw!r}") from exc


def _as_float(section: dict[str, Any], key: str, default: float) -> float:
    raw = section.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"配置项 '{key}' 应为数字，实际为 {raw!r}") from exc


def parse_settings(data: dict[str, Any], source: Path | None = None) -> Settings:
    """把原始 dict 解析为 Settings，缺失字段回落到默认值。"""
    if not isinstance(data, dict):
        raise ConfigError("配置文件根节点应为 JSON 对象")

    urls = dict(DEFAULT_URLS)
    urls.update(_as_section(data, "url"))

    headers = dict(DEFAULT_HEADERS)
    headers.update(_as_section(data, "basic_headers"))

    net_raw = _as_section(data, "network")
    network = NetworkConfig(
        connect_timeout=_as_float(net_raw, "connect_timeout", 5.0),
        read_timeout=_as_float(net_raw, "read_timeout", 15.0),
        retries=_as_int(net_raw, "retries", 3),
        backoff_factor=_as_float(net_raw, "backoff_factor", 0.5),
    )

    aria2_raw = _as_section(data, "aria2")
    extra_args = aria2_raw.get("extra_args", [])
    if not isinstance(extra_args, list):
        raise ConfigError("配置项 'aria2.extra_args' 应为字符串数组")
    aria2 = Aria2Config(
        split=_as_int(aria2_raw, "split", 8),
        max_connection_per_server=_as_int(aria2_raw, "max_connection_per_server", 2),
        rpc_port=_as_int(aria2_raw, "rpc_port", 0),
        startup_timeout=_as_float(aria2_raw, "startup_timeout", 10.0),
        poll_interval=_as_float(aria2_raw, "poll_interval", 0.4),
        extra_args=[str(a) for a in extra_args],
    )

    # 旧配置把输出目录放在 video.video_path，这里保持兼容
    dl_raw = _as_section(data, "download")
    legacy_video = _as_section(data, "video")
    download = DownloadConfig(
        output_dir=str(
            dl_raw.get("output_dir", legacy_video.get("video_path", "video"))
        ),
        concurrent_downloads=_as_int(dl_raw, "concurrent_downloads", 3),
        mux_workers=_as_int(dl_raw, "mux_workers", 2),
    )

    return Settings(
        urls=urls,
        headers=headers,
        network=network,
        aria2=aria2,
        download=download,
        source_path=source,
    )


def load_settings(path: Path = CONFIG_FILE) -> Settings:
    """从磁盘加载配置；文件不存在时使用全默认值。"""
    if not path.exists():
        return parse_settings({}, source=path)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"配置文件 {path} 不是合法的 JSON: {exc}",
            hint=f"请检查第 {exc.lineno} 行第 {exc.colno} 列附近的语法。",
        ) from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc

    return parse_settings(raw, source=path)
