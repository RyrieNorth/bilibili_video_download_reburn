"""B站视频接口封装。"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import Settings
from ..errors import ApiError, ArgumentError
from ..utils.log import get_logger
from ..utils.models import AUDIO_LABELS, Page, QualityOption, Stream

logger = get_logger("api")

BV_PATTERN = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_PATTERN = re.compile(r"^av(\d+)$", re.IGNORECASE)
SEASON_PATTERN = re.compile(r"^(ss|ep)(\d+)$", re.IGNORECASE)

# 该值用于向B站API请求所有可用的DASH音视频流（视频、音频、字幕等）。
# 值为 4048，对应多个选项的位或运算结果，具体含义可参考：
# https://janson20.github.io/bilibili-api-collect-mirror/docs/video/videostream_url.html
FNVAL_DASH_ALL = 4048


def normalize_video_id(raw: str) -> tuple[str, str]:
    """
    将用户输入的任意视频/剧集标识符归一化为标准类型和ID。
    
    支持以下输入格式：
    - BV号（如 "BV1q4411N7B5"）
    - av号（如 "av123456"）
    - 番剧季号（"ss123"）或集号（"ep456"）
    - 完整页面URL（自动从URL中提取上述标识符）
    
    参数:
        raw (str): 用户输入的原始字符串，可为空或None（视为空）。

    返回:
        tuple[str, str]: (类型, ID)，类型为 "bv" / "av" / "ss" / "ep" 之一。

    异常:
        ArgumentError: 当输入为空、无法解析或格式不支持时抛出。

    处理优先级（按顺序）:
        1. 从文本中搜索BV号（支持URL片段）
        2. 从URL路径中提取ss/ep（如 "/ss123" 或 "/ep456"）
        3. 直接匹配完整的ss/ep字符串（如 "ss123"）
        4. 直接匹配完整的av号（如 "av123"）
        5. 从URL路径中提取av号（如 "/av123"）
        6. 若均不匹配，抛出异常。
    """
    text = (raw or "").strip()
    
    if not text:
        raise ArgumentError("未提供视频 ID", hint="请传入 BV 号、av 号或番剧的 ss/ep 号。")

    # 从输入 URL 中匹配 bvid
    if match := BV_PATTERN.search(text):
        return "bv", match.group(1)

    # 解析番剧类型: ss/ep
    if match := re.search(r"/(ss|ep)(\d+)", text, re.IGNORECASE):
        return match.group(1).lower(), f"{match.group(1).lower()}{match.group(2)}"

    # 匹配完整的 ss/ep 字符串
    if match := SEASON_PATTERN.match(text):
        return match.group(1).lower(), text.lower()

    # 解析 av 号
    if match := AV_PATTERN.match(text):
        return "av", match.group(1)

    # 从 URL 路径中提取 av 号
    if match := re.search(r"/av(\d+)", text, re.IGNORECASE):
        return "av", match.group(1)

    raise ArgumentError(
        f"无法识别的视频 ID: {raw}",
        hint="支持 BV 号、av 号、番剧 ss/ep 号，或直接粘贴视频页面链接。",
    )


class BiliClient:
    """B站 HTTP API 调用逻辑。"""

    def __init__(self, settings: Settings, cookies: dict[str, str] | None = None):
        self.settings = settings
        self.cookies = cookies or {}
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(self.settings.headers)
        if self.cookies:
            session.cookies.update(self.cookies)

        retry = Retry(
            total=self.settings.network.retries,
            backoff_factor=self.settings.network.backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> BiliClient:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def cookie_header(self) -> str:
        """拼接 Cookie 请求头，供 aria2c 下载时携带登录态。"""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict:
        """发起 GET 并返回解析后的 JSON，失败统一转成 ApiError。"""
        started = time.monotonic()
        try:
            response = self.session.get(
                url, params=params, timeout=self.settings.network.timeout
            )
        except requests.exceptions.Timeout as exc:
            raise ApiError(
                f"请求超时: {url}",
                url=url,
                hint="网络较慢或被限流，可稍后重试。或调大 config.json 的 network.read_timeout。",
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ApiError(
                f"网络连接失败: {url}",
                url=url,
                hint="请检查网络连通性或代理设置。",
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ApiError(f"请求失败: {exc}", url=url) from exc

        elapsed = (time.monotonic() - started) * 1000
        logger.debug(
            f"GET {url} params={params} -> {response.status_code} ({elapsed:.0f}ms)"
        )

        if response.status_code >= 400:
            raise ApiError(
                f"HTTP {response.status_code}: {url}",
                url=url,
                hint="接口地址可能已变更，或触发了访问频率限制。",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            snippet = response.text[:200]
            raise ApiError(
                f"响应不是合法 JSON: {snippet!r}",
                url=url,
                hint="可能被网络中间层拦截并返回了 HTML 页面。",
            ) from exc

        if not isinstance(payload, dict):
            raise ApiError(f"响应结构异常：{type(payload).__name__}", url=url)

        return payload

    def get_data(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET 并校验业务码，返回 data 字段。"""
        payload = self.get_json(url, params)
        code = payload.get("code")

        if code not in (0, None):
            message = payload.get("message") or payload.get("msg") or "未知错误"
            raise ApiError(f"接口返回错误 {code}: {message}", code=code, url=url)

        if "data" not in payload and "result" not in payload:
            raise ApiError("缺少 'data' 字段", url=url)

        return payload.get("data", payload.get("result"))


    def get_video_view(self, video_type: str, video_id: str) -> dict:
        """调用 view 接口，获取标题、封面与分P列表。"""
        params = {"bvid": video_id} if video_type == "bv" else {"aid": video_id}
        data = self.get_data(self.settings.url("video_info"), params)
        if not isinstance(data, dict):
            raise ApiError("view 接口返回结构异常")
        return data


    def get_ai_subtitle(self, aid: int, cid: int, auth_key: str):
        pass

    def get_pages(self, video_type: str, video_id: str) -> tuple[str, list[Page]]:
        """返回 (稿件标题, 分P列表)。单P时列表长度为 1。"""
        view = self.get_video_view(video_type, video_id)
        bvid = view.get("bvid") or (video_id if video_type == "bv" else None)
        title = view.get("title") or bvid or "untitled"

        raw_pages = view.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            # view 接口异常时退回到 pagelist 接口
            raw_pages = self._get_pagelist(bvid or video_id)

        pages: list[Page] = []
        for index, item in enumerate(raw_pages, start=1):
            if not isinstance(item, dict) or "cid" not in item:
                raise ApiError(f"第 {index} 个分P缺少 cid 字段")
            pages.append(
                Page(
                    cid=int(item["cid"]),
                    index=int(item.get("page", index)),
                    title=item.get("part") or item.get("title") or f"P{index}",
                    duration=int(item.get("duration", 0) or 0),
                    bvid=bvid,
                )
            )

        # 单P稿件的 part 常常是空串，回退至稿件标题
        if len(pages) == 1 and (not pages[0].title or pages[0].title == "P1"):
            pages[0] = Page(
                cid=pages[0].cid,
                index=pages[0].index,
                title=title,
                duration=pages[0].duration,
                bvid=bvid,
            )

        logger.debug(f"{title}: 解析到 {len(pages)} 个分P")
        return title, pages

    def _get_pagelist(self, bvid: str) -> list[dict]:
        data = self.get_data(self.settings.url("convert_cid"), {"bvid": bvid})
        if not isinstance(data, list) or not data:
            raise ApiError(
                "pagelist 接口未返回分P信息",
                hint="请确认该稿件是否存在或已被删除。",
            )
        return data


    def get_playurl(self, bvid: str, cid: int, quality: int = 127) -> dict:
        """获取 dash 播放信息。qn 传高值以便拿到完整的可选清晰度列表。默认 qn=127，即 8K 超高清"""
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": quality,
            "fnval": FNVAL_DASH_ALL,
            "fnver": 0,
            "fourk": 1,
        }
        data = self.get_data(self.settings.url("play_api"), params)
        if not isinstance(data, dict):
            raise ApiError("playurl 接口返回结构异常")
        if "dash" not in data:
            raise ApiError(
                "playurl 未返回 dash 流",
                hint="该稿件可能只提供 flv/mp4 格式，或需要登录/付费后才能获取。",
            )
        return data

    def get_quality_options(self, playurl: dict) -> list[QualityOption]:
        """组装 accept_quality / accept_description 为可展示的清晰度选项。

        当视频处于 dash.video 中才标记为可下载。
        """
        ids = playurl.get("accept_quality") or []
        labels = playurl.get("accept_description") or []
        dash_ids = {
            int(v["id"])
            for v in (playurl.get("dash", {}).get("video") or [])
            if isinstance(v, dict) and "id" in v
        }

        options: list[QualityOption] = []
        for index, quality_id in enumerate(ids):
            quality_id = int(quality_id)
            label = labels[index] if index < len(labels) else f"qn={quality_id}"
            options.append(
                QualityOption(
                    quality_id=quality_id,
                    label=label,
                    available=quality_id in dash_ids,
                    needs_vip=quality_id >= 112,
                )
            )

        if not options:
            raise ApiError("playurl 未返回可选清晰度列表")
        return options

    def parse_streams(self, playurl: dict) -> tuple[list[Stream], list[Stream]]:
        """从 dash 段解析视频流列表与 音频流列表。"""
        dash = playurl.get("dash") or {}

        videos = [
            self._to_stream(item, "video")
            for item in (dash.get("video") or [])
            if isinstance(item, dict) and item.get("baseUrl")
        ]

        audio_items = list(dash.get("audio") or [])
        # 杜比与无损音轨在独立的字段里
        if dolby := dash.get("dolby"):
            audio_items.extend(dolby.get("audio") or [])
        if flac := dash.get("flac"):
            if isinstance(flac.get("audio"), dict):
                audio_items.append(flac["audio"])

        audios = [
            self._to_stream(item, "audio")
            for item in audio_items
            if isinstance(item, dict) and item.get("baseUrl")
        ]

        logger.debug(f"解析到 {len(videos)} 路视频流、{len(audios)} 路音频流")
        return videos, audios

    @staticmethod
    def _to_stream(item: dict, kind: str) -> Stream:
        stream_id = int(item.get("id", 0))
        codec = item.get("codecs", "") or ""
        label = (
            AUDIO_LABELS.get(stream_id, f"id={stream_id}")
            if kind == "audio"
            else f"{item.get('height', 0)}P"
        )
        backup = item.get("backupUrl") or item.get("backup_url") or []
        if isinstance(backup, str):
            backup = [backup]

        return Stream(
            url=item["baseUrl"],
            stream_id=stream_id,
            kind=kind,
            codec=codec,
            bandwidth=int(item.get("bandwidth", 0) or 0),
            label=label,
            width=int(item.get("width", 0) or 0),
            height=int(item.get("height", 0) or 0),
            backup_urls=tuple(backup),
        )

    def get_playurls_parallel(
        self, bvid: str, pages: list[Page], quality: int = 127, workers: int = 4
    ) -> dict[int, dict | Exception]:
        """并发拉取多个分P的播放信息，返回 {cid: playurl 或异常}。

        单个分P失败不影响其他分P，失败项以异常对象返回，由上层决定跳过还是中止。
        """
        if not pages:
            return {}
        if len(pages) == 1:
            page = pages[0]
            return {page.cid: self.get_playurl(page.bvid or bvid, page.cid, quality)}

        results: dict[int, dict | Exception] = {}
        max_workers = max(1, min(workers, len(pages)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self.get_playurl, page.bvid or bvid, page.cid, quality
                ): page
                for page in pages
            }
            for future, page in futures.items():
                try:
                    results[page.cid] = future.result()
                except Exception as exc:
                    logger.debug(f"P{page.index} 播放地址获取失败: {exc}")
                    results[page.cid] = exc
        return results

    def get_season_episodes(self, id_type: str, season_id: str) -> tuple[str, list[Page]]:
        """获取番剧剧集列表，返回 (剧名, 剧集列表)。只请求一次 season 接口。"""
        number = season_id[2:]
        params = {"ep_id": number} if id_type == "ep" else {"season_id": number}

        payload = self.get_json(self.settings.url("get_anime"), params)
        code = payload.get("code")
        if code not in (0, None):
            message = payload.get("message") or "未知错误"
            raise ApiError(
                f"番剧接口返回错误 {code}: {message}",
                code=code,
                hint="该番剧可能属于港澳台/海外限定，请尝试设置系统代理。",
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise ApiError(
                "番剧接口返回结构异常",
                hint="请确认 ss/ep 号是否正确，或该番剧是否有地区限制。",
            )

        title = result.get("title") or season_id
        episodes = result.get("episodes")
        if not isinstance(episodes, list) or not episodes:
            raise ApiError(
                f"番剧 '{title}' 暂无可下载剧集",
                hint="番剧尚未更新，或需要大会员权限才能看到剧集列表。",
            )

        pages: list[Page] = []
        for index, item in enumerate(episodes, start=1):
            if not isinstance(item, dict) or "cid" not in item:
                continue
            long_title = item.get("long_title") or ""
            short = item.get("title") or str(index)
            name = f"第{short}话 {long_title}".strip() if long_title else f"第{short}话"
            pages.append(
                Page(
                    cid=int(item["cid"]),
                    index=index,
                    title=name,
                    duration=int(item.get("duration", 0) or 0) // 1000,
                    bvid=item.get("bvid"),
                )
            )

        if not pages:
            raise ApiError(f"番剧 '{title}' 的剧集数据缺少 cid，无法下载")

        logger.debug(f"{title}: 解析到 {len(pages)} 集")
        return title, pages
