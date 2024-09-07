# Bilibili 视频下载工具

这是一个用于下载 Bilibili 视频的 Python 工具，支持单 P 和多 P 视频的下载及合并。该工具依赖于 [SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) 提供的 Bilibili API。

## 功能

- 支持单 P 和多 P 视频下载
- 支持视频和音频分开下载
- 自动选择视频质量
- 合并视频和音频为 MP4 格式

## 环境要求

- Python 3.6 或更高版本
- `requests` 库
- `Aria2c` 工具（用于下载视频）
- `FFmpeg` 工具（用于合并视频和音频）

## 安装

1. 克隆这个仓库：

   ```bash
   git clone https://github.com/NorthSky-Ryrie/bilibili_video_download_reburn.git
   cd bilibili_video_download_reburn
   python setup.py install

   
