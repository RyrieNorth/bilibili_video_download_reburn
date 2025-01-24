#!/usr/bin/env python
import argparse
import time
import sys
from multiprocessing import Process
from .utils import load_config
from .modules import (
    get_video_data,
    get_video_info,
    get_video_download_info,
    get_anime_info,
    get_user_quality_choice,
    run_download,
    merge_video,
)

config = load_config()


def parse_args():
    parser = argparse.ArgumentParser(description="B站视频下载工具")
    parser.add_argument("bv", help="视频的BV号")
    return parser.parse_args()


def main(video_id):
    try:
        if video_id.startswith("BV"):
            video_data, is_single_part = get_video_data(
                video_id,
                url=config["url"]["convert_cid"],
                header=config["basic_headers"],
            )
            video_info = get_video_info(
                video_id,
                video_data[0]["cid"] if not is_single_part else video_data["cid"],
            )
            quality_list = video_info["data"]["accept_description"]
            quality_ids = video_info["data"]["accept_quality"]

            selected_quality_id = get_user_quality_choice(quality_list, quality_ids)

            if is_single_part:
                video_title = video_data["part"]
                video_url, audio_url = get_video_download_info(
                    video_id, video_data, selected_quality_id
                )

                if video_url and audio_url:
                    run_download(video_url, audio_url, video_title)
                    merge_video(video_title)
                    print("视频下载完成, 视频文件存放在当前路径的'video'文件夹中")
            else:
                for video in video_data:
                    video_title = video["part"]
                    video_url, audio_url = get_video_download_info(
                        video_id, video, selected_quality_id
                    )

                    if video_url and audio_url:
                        p1 = Process(
                            target=run_download(video_url, audio_url, video_title)
                        )
                        p2 = Process(target=merge_video(video_title))
                        p1.start()
                        p2.start()
                        p1.join()
                        p2.join()
                        time.sleep(0.75)
                    else:
                        for i in quality_ids:
                            video_url, audio_url = get_video_download_info(
                                video_id, video, i
                            )
                            if video_url and audio_url:
                                p1 = Process(
                                    target=run_download(
                                        video_url, audio_url, video_title
                                    )
                                )
                                p2 = Process(target=merge_video(video_title))
                                p1.start()
                                p2.start()
                                p1.join()
                                p2.join()
                                time.sleep(0.75)
                                break
                        print(
                            "全部视频下载完成, 视频文件存放在当前路径的'video'文件夹中"
                        )

        elif video_id.startswith("ep") or video_id.startswith("ss"):
            anime_bvs = get_anime_info(video_id)

            # 调用视频下载方法处理每集
            for bvid in anime_bvs:
                main(bvid)

    except Exception as e:
        print(f"发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    if args.bv:
        main(args.bv)
