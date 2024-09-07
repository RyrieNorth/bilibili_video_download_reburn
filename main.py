import argparse
import requests
import json
import os
import sys
import logging
from tools_wrapper import Aria2c, FFmpeg
from utils import login_action, is_login

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 配置文件路径
CONFIG_FILE = "config.json"
COOKIE_FILE = "cookie.json"

def load_config(file_path=CONFIG_FILE):
    """加载配置文件，并检查文件是否存在"""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"配置文件 {file_path} 不存在，请检查路径。")
    
    with open(file_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    return config

def load_cookie(file_path=COOKIE_FILE):
    """加载cookie，并检查文件是否存在"""
    if not os.path.isfile(file_path):
        logging.info("Cookie 文件不存在，正在进行登录...")
        login_action()
        return None

    session = requests.Session()
    res = is_login(session)
    if res:
        logging.info(res)
        with open(file_path, "r", encoding="utf-8") as f:
            cookie = json.load(f)
        return cookie
    else:
        logging.warning("Cookies 值已经失效，请重新扫码登录！")
        login_action()
        return None

try:
    cookie = load_cookie("cookie.json")
    config = load_config("config.json")
except Exception as e:
    print(f"发生错误: {e}")
    sys.exit(1)


def parse_args():
    parser = argparse.ArgumentParser(description="下载B站视频工具")
    parser.add_argument("bv", help="视频的BV号")
    return parser.parse_args()

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
    response = requests.get(config["url"]["play_api"], params=payload, headers=config["basic_headers"], cookies=cookie).json()
    return response

def get_video_part_info(video_bv):
    payload = {"bvid": video_bv}
    response = requests.get(config["url"]["video_info"], params=payload, headers=config["basic_headers"], cookies=cookie).json()
    return response

def get_video_download_info(video_bv, video_data, selected_quality_id):
    video_cid = video_data["cid"]
    video_info = get_video_info(video_bv, video_cid)

    video_url = next((video["baseUrl"] for video in video_info["data"]["dash"]["video"] if video["id"] == selected_quality_id), None)
    audio_id = 30280 if selected_quality_id >= 80 else 30216 if selected_quality_id == 64 else 30232
    audio_url = next((audio["baseUrl"] for audio in video_info["data"]["dash"]["audio"] if audio["id"] == audio_id), None)

    return video_url, audio_url

def get_user_quality_choice(quality_list, quality_ids):
    logging.info("请选择你要下载的视频清晰度：")
    for idx, desc in enumerate(quality_list, 1):
        print(f"{idx}. {desc}")
    print("默认下载最高质量视频 (1)")

    user_choice = input(f"请输入选项 (1-{len(quality_list)}), 默认为 1: ").strip()
    return quality_ids[int(user_choice) - 1] if user_choice.isdigit() and 1 <= int(user_choice) <= len(quality_list) else quality_ids[0]

def create_video_directory():
    video_path = os.path.join(os.getcwd(), "video")
    if not os.path.exists(video_path):
        os.makedirs(video_path)
    return video_path

def run_download(video_url, audio_url, video_title, download_path=config["video"]["video_path"], referer=config["basic_headers"]["referer"], aria2c_config=config["aria2c"]):
    if not os.path.exists(download_path):
        create_video_directory()

    aria2c = Aria2c(download_path, referer, aria2c_config)
    video_code = aria2c.download_video(video_title, video_url)
    audio_code = aria2c.download_audio(video_title, audio_url)

    logging.info(f"视频: {video_title}.m4s {'下载成功' if video_code == 0 else '下载失败'}")
    logging.info(f"音频: {video_title}_audio.m4s {'下载成功' if audio_code == 0 else '下载失败'}")

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
        logging.error(f"视频: {video_title}.mp4 转码失败, 请检查音视频流是否异常或文件路径是否正确!")

def main(video_bv):
    try:
        video_data, is_single_part = get_video_data(video_bv, url=config["url"]["convert_cid"], header=config["basic_headers"])
        video_info = get_video_info(video_bv, video_data[0]["cid"] if not is_single_part else video_data["cid"])
        quality_list = video_info["data"]["accept_description"]
        quality_ids = video_info["data"]["accept_quality"]

        selected_quality_id = get_user_quality_choice(quality_list, quality_ids)

        if is_single_part:
            video_title = video_data["part"]
            video_url, audio_url = get_video_download_info(video_bv, video_data, selected_quality_id)

            if video_url and audio_url:
                run_download(video_url, audio_url, video_title)
                merge_video(video_title)
        else:
            video_part_info = get_video_part_info(video_bv)
            video_part_folder = os.path.join(config['video']['video_path'], video_part_info['data']['title'])

            if not os.path.exists(video_part_folder):
                os.makedirs(video_part_folder)

            for video in video_data:
                video_title = video["part"]
                video_url, audio_url = get_video_download_info(video_bv, video, selected_quality_id)

                if video_url and audio_url:
                    run_download(video_url, audio_url, video_title, video_part_folder)
                    merge_video(video_title, video_part_folder)
                else:
                    for i in quality_ids:
                        video_url, audio_url = get_video_download_info(video_bv, video, i)
                        if video_url:
                            run_download(video_url, audio_url, video_title, video_part_folder)
                            merge_video(video_title, video_part_folder)
                            break

    except Exception as e:
        logging.error(f"发生错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    args = parse_args()
    if args.bv:
        main(args.bv)
    else:
        logging.error("请输入视频BV号")
        logging.error("用法: python main.py <BV号>")
        sys.exit(1)
