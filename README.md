# bilibili_video_download_reburn

一个简单的用于下载 Bilibili 视频的 Python 工具，支持单P与多P视频下载 </br>
基于 [SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) 开发

## 功能

- 支持单P与多P视频下载
- 支持视频和音频分开下载
- 自动选择视频质量
- 合并视频和音频为 MP4 格式

## 环境要求

- Python 3.6 或更高版本
- `requests`, `qrcode`, windows 还会需要`PyQt5, PyQt5-tools` 库
- `Aria2c` 工具（用于下载视频）（已集成在tools文件夹中）
- `FFmpeg` 工具（用于合并视频和音频）（已集成在tools文件夹中且已经过裁剪）

## 安装方式

1. 克隆安装：

   ```bash
   git clone https://github.com/NorthSky-Ryrie/bilibili_video_download_reburn.git
   cd bilibili_video_download_reburn
   python setup.py install

2. 从release中下载安装：

   ```bash
   cd bilibili_video_download_reburn
   python setup.py install
