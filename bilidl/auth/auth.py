"""Cookies 的加载、校验与持久化。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import requests

from ..config import COOKIES_FILE, Settings
from ..errors import AuthError
from ..utils.log import get_logger
from ..utils.qrlogin import login_interactive

logger = get_logger("auth")


@dataclass
class LoginState:
    """当前登录态。username 为 None 表示以游客身份继续。"""

    cookies: dict[str, str]
    username: str | None = None
    is_vip: bool = False

    @property
    def logged_in(self) -> bool:
        return bool(self.cookies) and self.username is not None

    @property
    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())


class CookieStore:
    """负责 cookie.json 的读写。"""

    def __init__(self, path: Path = COOKIES_FILE):
        self.path = path

    def read(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(f"{self.path} 不是合法 JSON，将忽略并重新登录: {exc}")
            return {}
        except OSError as exc:
            logger.warning(f"无法读取 {self.path}: {exc}")
            return {}

        if not isinstance(data, dict):
            logger.warning(f"{self.path} 结构异常（应为对象），将忽略")
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def write(self, cookies: dict[str, str]) -> None:
        try:
            self.path.write_text(
                json.dumps(cookies, indent=4, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            # 存不下来不影响本次运行，下次重新扫码
            logger.warning(f"Cookies 保存失败（本次仍可正常下载）: {exc}")
        else:
            logger.debug(f"Cookies 已保存到 {self.path}")

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"无法删除 {self.path}: {exc}")


class Authenticator:
    """校验已有 Cookies，必要时触发扫码登录。"""

    def __init__(self, settings: Settings, store: CookieStore | None = None):
        self.settings = settings
        self.store = store or CookieStore()

    def resolve(self, allow_login: bool = True, force_login: bool = False) -> LoginState:
        """返回可用的登录态。

        allow_login=False 时不会弹出扫码（适合脚本/非交互场景），
        Cookies 失效则降级为游客身份并给出警告。
        """
        if force_login:
            return self._login(allow_login=True)

        cookies = self.store.read()
        if not cookies:
            logger.info("未找到本地 Cookies")
            return self._login(allow_login)

        username, is_vip, vip_type = self.check_login(cookies)
        if username:
            logger.info(f"Cookies 有效，当前用户: {username} {f"({vip_type})" if is_vip else ''}")
            return LoginState(cookies=cookies, username=username, is_vip=is_vip)

        logger.warning("本地 Cookies 已失效")
        return self._login(allow_login)

    def _login(self, allow_login: bool) -> LoginState:
        if not allow_login:
            logger.warning("未登录，将以游客身份继续（仅能下载低清晰度）")
            return LoginState(cookies={})

        cookies = login_interactive(self.settings)
        if not cookies:
            raise AuthError(
                "未完成登录",
                hint="可加 --no-login 以游客身份继续，但清晰度会受限。",
            )

        username, is_vip = self.check_login(cookies)
        if not username:
            raise AuthError(
                "登录后校验仍未通过，Cookies 可能不完整",
                hint="请重新运行并重新扫码。",
            )

        self.store.write(cookies)
        return LoginState(cookies=cookies, username=username, is_vip=is_vip)

    def check_login(self, cookies: dict[str, str]) -> tuple[str | None, bool]:
        """请求 nav 接口校验登录态，返回 (用户名, 是否大会员)。"""
        session = requests.Session()
        session.headers.update(self.settings.headers)
        session.cookies.update(cookies)

        try:
            response = session.get(
                self.settings.url("login_url"), timeout=self.settings.network.timeout
            )
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            # 网络问题不等于 Cookies 失效，这里不擦除本地凭据
            logger.warning(f"登录校验请求失败，暂按未登录处理: {exc}")
            return None, False
        except ValueError:
            logger.warning("登录校验响应不是合法 JSON")
            return None, False
        finally:
            session.close()

        if payload.get("code") != 0:
            logger.debug(f"nav 接口返回 code={payload.get('code')}")
            return None, False

        data = payload.get("data") or {}
        if not data.get("isLogin"):
            return None, False

        vip = data.get("vipStatus") or (data.get("vip") or {}).get("status")
        vip_type = data.get("vip_label")["text"]
        return data.get("uname"), bool(vip), vip_type
