"""统一异常体系。"""


class BiliDLError(Exception):
    """全局异常配置。"""

    exit_code = 1

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message


class ConfigError(BiliDLError):
    """config.json 配置文件缺失或格式异常。"""

    exit_code = 2


class ArgumentError(BiliDLError):
    """命令行参数非法。"""

    exit_code = 2


class AuthError(BiliDLError):
    """登录状态缺失或扫码登录失败。"""

    exit_code = 3


class ApiError(BiliDLError):
    """B站接口回调错误码，或响应结构不符合预期。"""

    exit_code = 3

    # 常见业务码 -> 中文提示
    CODE_HINTS = {
        -400: "请求参数有误，请确认输入的 ID 是否完整。",
        -403: "访问被拒绝，该内容可能有地区或权限限制。",
        -404: "稿件不存在，可能已被删除或 ID 输入错误。",
        -352: "被风控拦截，请稍后重试或重新扫码登录。",
        62002: "稿件不可见（可能是私有或审核中）。",
        62004: "稿件正在审核中，暂时无法下载。",
        87008: "该清晰度需要大会员权限。",
        10403: "受地区限制，请尝试设置系统代理。",
    }

    def __init__(
        self,
        message: str,
        code: int | None = None,
        url: str | None = None,
        hint: str | None = None,
    ):
        self.code = code
        self.url = url
        if hint is None and code is not None:
            hint = self.CODE_HINTS.get(code)
        super().__init__(message, hint)


class ToolNotFoundError(BiliDLError):
    """aria2c / ffmpeg 可执行文件缺失。"""

    exit_code = 4


class Aria2Error(BiliDLError):
    """aria2c 守护进程启动失败或 RPC 调用异常。"""

    exit_code = 5


class DownloadError(BiliDLError):
    """下载任务失败。"""

    exit_code = 5

    def __init__(
        self,
        message: str,
        filename: str | None = None,
        error_code: str | None = None,
        hint: str | None = None,
    ):
        self.filename = filename
        self.error_code = error_code
        super().__init__(message, hint)


class MuxError(BiliDLError):
    """ffmpeg 合并失败，stderr_tail 保留最后若干行输出便于排查。"""

    exit_code = 6

    def __init__(
        self,
        message: str,
        stderr_tail: str | None = None,
        hint: str | None = None,
    ):
        self.stderr_tail = stderr_tail
        super().__init__(message, hint)
