import requests
import logging
import os
import re
import sys
from .tools_wrapper import Aria2c, FFmpeg
from .utils import load_cookie, load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

cookie = load_cookie()
config = load_config()


def get_video_data(video_bv, url, header):
    params = {"bvid": video_bv}
    response = requests.get(url, headers=header, params=params).json()

    if "data" not in response:
        raise ValueError("Response does not contain 'data' field")

    res_data = response["data"]

    if isinstance(res_data, list):
        if len(res_data) == 1:
            logging.info("检测视频为单P视频")
            return res_data[0], True
        else:
            logging.info("检测视频为多P视频")
            return res_data, False
    else:
        raise ValueError("Unexpected data structure in response")


def get_video_info(video_bv, video_cid, video_hd="64"):
    payload = {
        "bvid": video_bv,
        "cid": video_cid,
        "qn": video_hd,
        "fnval": "16",
        "fnver": "0",
        "fourk": "1",
    }
    response = requests.get(
        config["url"]["play_api"],
        params=payload,
        headers=config["basic_headers"],
        cookies=cookie,
    ).json()
    return response


def get_video_part_info(video_bv):
    payload = {"bvid": video_bv}
    response = requests.get(
        config["url"]["video_info"],
        params=payload,
        headers=config["basic_headers"],
        cookies=cookie,
    ).json()
    return response


def get_video_download_info(video_bv, video_data, selected_quality_id):
    video_cid = video_data["cid"]
    video_info = get_video_info(video_bv, video_cid)

    video_url = next(
        (
            video["baseUrl"]
            for video in video_info["data"]["dash"]["video"]
            if video["id"] == selected_quality_id
        ),
        None,
    )
    audio_id = (
        30280
        if selected_quality_id >= 80
        else 30216 if selected_quality_id == 64 else 30232
    )
    audio_url = next(
        (
            audio["baseUrl"]
            for audio in video_info["data"]["dash"]["audio"]
            if audio["id"] == audio_id
        ),
        None,
    )

    return video_url, audio_url


def get_anime_data(anime_id, url, header):
    anime_type = re.sub(r"[0-9]", "", anime_id)
    if anime_type == "ep":
        logging.info("检测番剧类型为ep")
        params = {"ep_id": anime_id.replace("ep", "")}

    elif anime_type == "ss":
        logging.info("检测番剧类型为ss")
        params = {"season_id": anime_id.replace("ss", "")}

    response = requests.get(url, headers=header, params=params).json()

    if "result" not in response:
        logging.error("你输入的番剧ID有误, 或该番剧属于港澳台类型, 请尝试设置系统代理")
        sys.exit(1)

    res_data = response["result"]["episodes"]
    if isinstance(res_data, list):
        if len(res_data) == 0:
            logging.warning("当前番剧未更新")
            sys.exit(1)
        else:
            return res_data
    else:
        raise ValueError("Unexpected result structure in response")


def get_anime_info(anime_id):
    anime_info = get_anime_data(
        anime_id, config["url"]["get_anime"], config["basic_headers"]
    )

    anime_bv = []
    for i in range(len(anime_info)):
        anime_bv.append(anime_info[i]["bvid"])

    return anime_bv


def get_user_quality_choice(quality_list, quality_ids):
    logging.info("请选择你要下载的视频清晰度：")
    for idx, desc in enumerate(quality_list, 1):
        print(f"{idx}. {desc}")
    print("默认下载最高质量视频 (1)")

    user_choice = input(f"请输入选项 (1-{len(quality_list)}), 默认为 1: ").strip()
    return (
        quality_ids[int(user_choice) - 1]
        if user_choice.isdigit() and 1 <= int(user_choice) <= len(quality_list)
        else quality_ids[0]
    )


def init_video_dir():
    video_path = os.path.join(os.getcwd(), "video")
    if not os.path.exists(video_path):
        os.makedirs(video_path)
    return video_path


def run_download(
    video_url,
    audio_url,
    video_title,
    download_path=config["video"]["video_path"],
    referer=config["basic_headers"]["referer"],
    aria2c_config=config["aria2c"],
):
    if not os.path.exists(download_path):
        init_video_dir()

    aria2c = Aria2c(download_path, referer, aria2c_config)
    video_code = aria2c.download_video(video_title, video_url)
    audio_code = aria2c.download_audio(video_title, audio_url)

    logging.info(
        f"视频: {video_title}.m4s {'下载成功' if video_code == 0 else '下载失败'}"
    )
    logging.info(
        f"音频: {video_title}_audio.m4s {'下载成功' if audio_code == 0 else '下载失败'}"
    )


def merge_video(video_title, video_path=config["video"]["video_path"]):
    ffmpeg = FFmpeg(video_path)

    video_input_path = os.path.join(video_path, f"{video_title}.m4s")
    audio_input_path = os.path.join(video_path, f"{video_title}_audio.m4s")
    output_path = os.path.join(video_path, f"{video_title}.mp4")

    ffmpeg_code, _, _ = ffmpeg.run_ffmpeg_command(video_title)

    if ffmpeg_code == 0:
        logging.info(f"转码完毕，输出文件: {output_path}")
        os.remove(video_input_path)
        os.remove(audio_input_path)
    else:
        logging.error(
            f"视频: {video_title}.mp4 转码失败, 请检查音视频流是否异常或文件路径是否正确!"
        )
