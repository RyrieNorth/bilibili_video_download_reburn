#!/usr/bin/env python
from setuptools import setup

setup(
    name="bilibili_video_download_reburn",
    version="0.3",
    license="MIT",
    url="https://github.com/RyrieNorth/bilibili_video_download_reburn",
    description="A tool for downloading and processing Bilibili videos",
    platforms=["any"],
    author="RyrieNorth",
    author_email="bk15018708480@gmail.com",
    install_requires=[
        "requests",
        "qrcode",
    ],
    py_modules=["bilibili_video_download"],
    packages=["bilibili_video_download"],
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "bl_download = bilibili_video_download.cli:run",
        ],
    },
)
