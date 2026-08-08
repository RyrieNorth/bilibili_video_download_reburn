"""aria2c 常驻守护进程 + JSON-RPC 客户端。"""

from __future__ import annotations

import atexit
import json
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import Aria2Config
from ..errors import Aria2Error, DownloadError
from ..utils.log import get_logger
from ..paths import find_tool

logger = get_logger("aria2")

# aria2 状态: active / waiting / paused / error / complete / removed
TERMINAL_STATUSES = {"complete", "error", "removed"}

TELL_STATUS_KEYS = [
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "errorCode",
    "errorMessage",
    "files",
]

# aria2 常见错误码 -> 中文提示
ARIA2_ERROR_HINTS = {
    "1": "未知错误，可加 --debug 查看 aria2 日志。",
    "2": "操作超时，可能是网络不稳定。",
    "3": "资源不存在（404），播放地址可能已过期，请重试。",
    "8": "服务端不支持断点续传。",
    "9": "磁盘空间不足。",
    "22": "HTTP 响应异常（常见于 403），通常是缺少 Cookie 或 Referer。",
    "24": "HTTP 认证失败，请重新扫码登录。",
}


@dataclass
class TaskStatus:
    """单个 GID 的下载状态快照。"""

    gid: str
    status: str
    total: int
    completed: int
    speed: int
    error_code: str | None = None
    error_message: str | None = None

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def failed(self) -> bool:
        return self.status in {"error", "removed"}


def _pick_free_port() -> int:
    """让操作系统分配一个空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Aria2Rpc:
    """aria2 JSON-RPC over HTTP 客户端。"""

    def __init__(self, port: int, secret: str, timeout: float = 10.0):
        self.endpoint = f"http://127.0.0.1:{port}/jsonrpc"
        self.secret = secret
        self.timeout = timeout
        self.session = requests.Session()
        self._request_id = 0

    def close(self) -> None:
        self.session.close()

    @property
    def token(self) -> str:
        return f"token:{self.secret}"

    def _next_id(self) -> str:
        self._request_id += 1
        return str(self._request_id)

    def build_payload(self, method: str, params: list) -> dict:
        """构造 JSON-RPC 请求体（独立成函数便于单元测试）。"""
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": [self.token, *params],
        }

    def call(self, method: str, params: list | None = None) -> object:
        payload = self.build_payload(method, params or [])
        logger.debug(f"RPC -> {method} {json.dumps(params or [], ensure_ascii=False)}")

        try:
            response = self.session.post(
                self.endpoint, json=payload, timeout=self.timeout
            )
        except requests.exceptions.RequestException as exc:
            raise Aria2Error(
                f"aria2 RPC 调用失败 ({method}): {exc}",
                hint="aria2c 守护进程可能已退出，可加 --debug 查看详情。",
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise Aria2Error(f"aria2 RPC 返回非 JSON 内容: {response.text[:200]!r}") from exc

        if error := body.get("error"):
            raise Aria2Error(
                f"aria2 RPC 错误 ({method}): {error.get('message', error)}",
                hint="若提示 Unauthorized 说明 rpc-secret 不匹配。",
            )

        logger.debug(f"RPC <- {method} ok")
        return body.get("result")

    def multicall(self, calls: list[tuple[str, list]]) -> list:
        """用 system.multicall 把多个调用压缩成一次往返。

        注意 multicall 的每个子调用需要自带 token，且外层不再传 token。
        """
        methods = [
            {"methodName": name, "params": [self.token, *params]}
            for name, params in calls
        ]
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "system.multicall",
            "params": [methods],
        }
        logger.debug(f"RPC -> system.multicall x{len(methods)}")

        try:
            response = self.session.post(
                self.endpoint, json=payload, timeout=self.timeout
            )
            body = response.json()
        except requests.exceptions.RequestException as exc:
            raise Aria2Error(f"aria2 RPC multicall 失败: {exc}") from exc
        except ValueError as exc:
            raise Aria2Error("aria2 RPC multicall 返回非 JSON 内容") from exc

        if error := body.get("error"):
            raise Aria2Error(f"aria2 RPC multicall 错误: {error.get('message', error)}")

        return body.get("result") or []

    def get_version(self) -> str:
        result = self.call("aria2.getVersion")
        return (result or {}).get("version", "unknown")  # type: ignore[union-attr]

    def add_uri(self, uris: list[str], options: dict[str, object]) -> str:
        gid = self.call("aria2.addUri", [uris, options])
        if not isinstance(gid, str):
            raise Aria2Error(f"addUri 未返回合法 GID: {gid!r}")
        return gid

    def tell_status(self, gid: str) -> TaskStatus:
        raw = self.call("aria2.tellStatus", [gid, TELL_STATUS_KEYS])
        return _parse_status(raw)  # type: ignore[arg-type]

    def tell_status_batch(self, gids: list[str]) -> dict[str, TaskStatus]:
        """批量查询状态，一次网络往返拿全部 GID。"""
        if not gids:
            return {}
        calls = [("aria2.tellStatus", [gid, TELL_STATUS_KEYS]) for gid in gids]
        results = self.multicall(calls)

        statuses: dict[str, TaskStatus] = {}
        for gid, item in zip(gids, results):
            # multicall 的每个结果被包成单元素列表；出错时是 dict
            if isinstance(item, list) and item:
                statuses[gid] = _parse_status(item[0])
            elif isinstance(item, dict) and "faultString" in item:
                logger.debug(f"tellStatus({gid}) 失败: {item['faultString']}")
            else:
                logger.debug(f"tellStatus({gid}) 返回异常结构: {item!r}")
        return statuses

    def remove(self, gid: str) -> None:
        try:
            self.call("aria2.remove", [gid])
        except Aria2Error:
            pass  # 任务可能已经结束，忽略

    def pause_all(self) -> None:
        try:
            self.call("aria2.pauseAll")
        except Aria2Error:
            pass

    def shutdown(self) -> None:
        try:
            self.call("aria2.shutdown")
        except Aria2Error as exc:
            logger.debug(f"aria2.shutdown 调用失败（进程可能已退出）: {exc}")


def _parse_status(raw: dict) -> TaskStatus:
    def as_int(key: str) -> int:
        try:
            return int(raw.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    return TaskStatus(
        gid=str(raw.get("gid", "")),
        status=str(raw.get("status", "unknown")),
        total=as_int("totalLength"),
        completed=as_int("completedLength"),
        speed=as_int("downloadSpeed"),
        error_code=raw.get("errorCode"),
        error_message=raw.get("errorMessage"),
    )


class Aria2Daemon:
    """以 --enable-rpc 方式常驻的 aria2c 进程，用作上下文管理器。"""

    def __init__(self, config: Aria2Config, download_dir: Path, debug: bool = False):
        self.config = config
        self.download_dir = download_dir
        self.debug = debug
        self.executable = find_tool("aria2c")
        self.port = config.rpc_port or _pick_free_port()
        self.secret = secrets.token_urlsafe(24)
        self.process: subprocess.Popen | None = None
        self.rpc: Aria2Rpc | None = None
        # aria2c 的输出重定向到临时文件而非管道：管道满会阻塞 aria2c，
        # 且进程存活时 read() 会一直等到 EOF。
        self._log_path: Path | None = None
        self._log_handle = None


    def build_command(self) -> list[str]:
        """组装启动参数。全部以列表传入，不经过 shell。"""
        args = [
            str(self.executable),
            "--enable-rpc",
            "--rpc-listen-all=false",
            f"--rpc-listen-port={self.port}",
            f"--rpc-secret={self.secret}",
            f"--dir={self.download_dir}",
            "--continue=true",
            f"--split={self.config.split}",
            f"--max-connection-per-server={self.config.max_connection_per_server}",
            f"--max-concurrent-downloads={max(1, self.config.split)}",
            "--file-allocation=none",
            "--auto-file-renaming=false",
            "--allow-overwrite=true",
            # 自带的 aria2c 非 RHEL 编译，找不到系统 CA，故关闭证书校验
            "--check-certificate=false",
            "--summary-interval=0",
            "--console-log-level=warn" if self.debug else "--console-log-level=error",
            "--download-result=hide",
        ]
        args.extend(self.config.extra_args)
        return args

    def start(self) -> Aria2Rpc:
        if self.process is not None:
            raise Aria2Error("aria2c 守护进程已在运行")

        command = self.build_command()
        # 日志里隐去 rpc-secret，避免泄露到日志文件
        printable = [
            a if not a.startswith("--rpc-secret") else "--rpc-secret=***" for a in command
        ]
        logger.debug(f"启动 aria2c: {' '.join(printable)}")

        try:
            self._log_handle = tempfile.NamedTemporaryFile(
                mode="w",
                prefix="bilidl-aria2-",
                suffix=".log",
                encoding="utf-8",
                errors="replace",
                delete=False,
            )
            self._log_path = Path(self._log_handle.name)
            logger.debug(f"aria2c 输出日志: {self._log_path}")

            self.process = subprocess.Popen(
                command,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=False,
                creationflags=_no_window_flag(),
            )
        except OSError as exc:
            self._close_log()
            raise Aria2Error(
                f"无法启动 aria2c: {exc}",
                hint=f"请确认 {self.executable} 可执行。",
            ) from exc

        atexit.register(self.stop)
        self.rpc = Aria2Rpc(self.port, self.secret)
        self._wait_ready()
        return self.rpc

    def _wait_ready(self) -> None:
        """退避轮询 getVersion 直到就绪，超时则连同 aria2c 输出一起报错。"""
        assert self.rpc is not None
        deadline = time.monotonic() + self.config.startup_timeout
        interval = 0.1
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise Aria2Error(
                    f"aria2c 启动后立即退出（返回码 {self.process.returncode}）",
                    hint=self._failure_hint(),
                )
            try:
                version = self.rpc.get_version()
            except Aria2Error as exc:
                last_error = exc
                time.sleep(interval)
                interval = min(interval * 1.5, 0.8)
                continue
            else:
                logger.debug(f"aria2c {version} 已就绪，RPC 端口 {self.port}")
                return

        raise Aria2Error(
            f"aria2c 在 {self.config.startup_timeout:.0f}s 内未就绪: {last_error}",
            hint=(
                f"端口 {self.port} 可能被占用，可在 config.json 中设置 aria2.rpc_port，"
                "或调大 aria2.startup_timeout。"
            ),
        )

    def _failure_hint(self) -> str:
        output = self.read_log_tail()
        return f"aria2c 输出: {output}" if output else "可加 --debug 查看更多信息。"

    def read_log_tail(self, limit: int = 20) -> str:
        """读取 aria2c 输出日志的末尾若干行（不会阻塞，进程存活也可调用）。"""
        if self._log_path is None:
            return ""
        try:
            if self._log_handle is not None:
                self._log_handle.flush()
            content = self._log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        lines = [line for line in content.splitlines() if line.strip()]
        return "\n".join(lines[-limit:])

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None
        # 调试模式下保留日志文件便于排查，正常退出则清理
        if self._log_path is not None and not self.debug:
            try:
                self._log_path.unlink(missing_ok=True)
            except OSError:
                pass
            self._log_path = None

    def stop(self) -> None:
        """优雅关停：shutdown -> terminate -> kill，确保不留孤儿进程。"""
        if self.rpc is not None:
            self.rpc.shutdown()

        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.debug("aria2c 未响应 shutdown，改为 terminate")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    logger.warning("aria2c 无法终止，强制 kill")
                    process.kill()
                    process.wait(timeout=3)

        if self.rpc is not None:
            self.rpc.close()
            self.rpc = None

        self._close_log()

        try:
            atexit.unregister(self.stop)
        except Exception:
            pass

    def __enter__(self) -> Aria2Rpc:
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()


def _no_window_flag() -> int:
    """Windows 下避免弹出额外的控制台窗口。"""
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def build_download_options(
    filename: str,
    referer: str,
    user_agent: str,
    cookie_header: str = "",
) -> dict[str, object]:
    """构造 addUri 的 options。Cookie 必须带上，否则高清直链会 403。"""
    headers = []
    if cookie_header:
        headers.append(f"Cookie: {cookie_header}")

    options: dict[str, object] = {
        "out": filename,
        "referer": referer,
        "user-agent": user_agent,
    }
    if headers:
        options["header"] = headers
    return options


def describe_error(status: TaskStatus) -> DownloadError:
    """把失败状态转成带中文提示的 DownloadError。"""
    code = status.error_code or "?"
    message = status.error_message or "未知原因"
    return DownloadError(
        f"下载失败 (aria2 错误码 {code}): {message}",
        error_code=code,
        hint=ARIA2_ERROR_HINTS.get(code),
    )
