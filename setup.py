#!/usr/bin/env python
import os
from setuptools import setup

if os.name == "nt":  # Windows 系统
    package_data = {"": ["config.json", "tools/aria2c.exe", "tools/ffmpeg.exe"]}
else:
    package_data = {"": ["config.json", "tools/aria2c", "tools/ffmpeg"]}

setup(
    name="bilibili_video_download_reburn",
    version="0.4",
    license="MIT",
    url="https://github.com/RyrieNorth/bilibili_video_download_reburn",
    description="A tool for downloading and processing Bilibili videos",
    platforms=["any"],
    author="RyrieNorth",
    author_email="2586649501@qq.com",
    install_requires=[
        "requests",
        "qrcode",
    ],
    py_modules=["bilibili_video_download"],
    packages=["bilibili_video_download"],
    package_data=package_data,
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "bl_download = bilibili_video_download.cli:run",
        ],
    },
)
