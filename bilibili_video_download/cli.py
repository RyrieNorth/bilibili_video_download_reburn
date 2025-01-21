#!/usr/bin/env python
from bilibili_video_download.main import main
import argparse


def run():
    parser = argparse.ArgumentParser(description="B站视频下载工具")
    parser.add_argument("bv", type=str, help="视频的BV号")
    args = parser.parse_args()

    # 调用 main 函数并传递 bv 参数
    main(args.bv)


if __name__ == "__main__":
    run()
