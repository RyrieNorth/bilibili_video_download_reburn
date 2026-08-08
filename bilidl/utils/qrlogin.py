"""扫码登录：申请二维码、终端渲染、轮询登录状态。"""

from __future__ import annotations

import io
import time

import qrcode
import requests

from ..config import Settings
from ..errors import AuthError
from .log import get_logger
from .ui import get_console

logger = get_logger("qrlogin")

# 轮询接口状态码
CODE_SUCCESS = 0
CODE_NOT_SCANNED = 86101
CODE_WAIT_CONFIRM = 86090
CODE_EXPIRED = 86038

POLL_INTERVAL = 2.0  # 轮询间隔（秒）
MAX_REFRESH = 3  # 二维码最多自动重新生成的次数


def render_qrcode(data: str) -> str:
    """把链接渲染为可在终端显示的 ASCII 二维码。"""
    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make()
    buffer = io.StringIO()
    qr.print_ascii(out=buffer, tty=False, invert=True)
    return buffer.getvalue()


class QRLogin:
    """完整扫码登录流程。成功返回 cookies 字典，用户取消返回 None。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.console = get_console()
        self.session = requests.Session()
        self.session.headers.update(settings.headers)

    def run(self) -> dict[str, str] | None:
        try:
            qrcode_key, url = self._request_qrcode()
            self._show(url)
            return self._poll(qrcode_key)
        except KeyboardInterrupt:
            self.console.print("\n已取消登录。")
            return None
        finally:
            self.session.close()

    def _show(self, url: str) -> None:
        self.console.print(render_qrcode(url), highlight=False)
        self.console.print("请使用 Bilibili 手机客户端扫描上方二维码登录（Ctrl+C 取消）")

    def _request_qrcode(self) -> tuple[str, str]:
        payload = self._get_json(self.settings.url("get_qrcode"))
        if payload.get("code") != 0:
            raise AuthError(
                f"申请二维码失败: {payload.get('message') or payload}",
                hint="请检查网络连通性，或稍后重试。",
            )
        data = payload.get("data") or {}
        key, url = data.get("qrcode_key"), data.get("url")
        if not key or not url:
            raise AuthError("二维码接口返回结构异常，缺少 qrcode_key 或 url")
        logger.debug(f"已申请二维码 qrcode_key={key}")
        return key, url

    def _get_json(self, url: str, params: dict | None = None) -> dict:
        try:
            response = self.session.get(
                url, params=params, timeout=self.settings.network.timeout
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            raise AuthError(f"登录请求失败: {exc}", hint="请检查网络连通性。") from exc
        except ValueError as exc:
            raise AuthError("登录接口返回的不是合法 JSON") from exc

    def _poll(self, qrcode_key: str) -> dict[str, str] | None:
        last_code: int | None = None
        refreshed = 0

        while True:
            payload = self._get_json(
                self.settings.url("check_qrcode_scan"), {"qrcode_key": qrcode_key}
            )
            data = payload.get("data") or {}
            code = data.get("code")

            if code == CODE_SUCCESS:
                cookies = self.session.cookies.get_dict()
                if not cookies:
                    raise AuthError("登录成功但未取得 Cookies，请重试")
                logger.info("登录成功")
                return cookies

            if code == CODE_EXPIRED:
                refreshed += 1
                if refreshed > MAX_REFRESH:
                    raise AuthError(
                        "二维码连续多次失效，已放弃登录",
                        hint="请重新运行命令并尽快完成扫码。",
                    )
                logger.info("二维码已失效，正在重新生成...")
                qrcode_key, url = self._request_qrcode()
                self._show(url)
                last_code = None
                continue

            # 只在状态变化时打印，避免刷屏
            if code != last_code:
                message = {
                    CODE_NOT_SCANNED: "等待扫码...",
                    CODE_WAIT_CONFIRM: "已扫码，请在手机上确认登录...",
                }.get(code, f"登录状态码: {code}")
                logger.info(message)
                last_code = code

            time.sleep(POLL_INTERVAL)


def login_interactive(settings: Settings) -> dict[str, str] | None:
    """供外部调用的扫码登录入口。"""
    return QRLogin(settings).run()


__all__ = ["QRLogin", "login_interactive", "render_qrcode"]
