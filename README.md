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

## 配置文件详情

1. 默认配置
   ```bash
   {
     "url": {
       "get_qrcode": "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",   //获取二维码
       "check_qrcode_scan": "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",   //查询二维码状态
       "play_api": "https://api.bilibili.com/x/player/playurl",   //播放器api
       "convert_cid": "https://api.bilibili.com/x/player/pagelist",   //将bvid转为cid
       "login_url": "https://api.bilibili.com/x/web-interface/nav",   //查询用户登录状态
       "video_info": "https://api.bilibili.com/x/web-interface/view"   //查询视频详细信息
     },
     "basic_headers": {
       "user-agent": "Mozilla/5.0",
       "referer": "https://www.bilibili.com"   //b站视频的防盗链，勿删，否则视频会无法下载
     },
     "video": {
       "video_path": "video"   //视频的存放路径，可修改
     },
     "aria2c": {
       "continue": "true",   //是否启用aria2断点续传，该选项用于网络环境不好的情况下使用，建议为true
       "split": "16",   //分片下载，这里设置16片，最大可设32，过大的会话可能会被服务器限流
       "max_connection_per_server": "8"   //服务器最大连接数，某些地方的网络可能会限制会话，若出现视频下载未响应请调整，默认为5
     }
   }

## 使用方式

1. 运行主程序脚本下载视频
   ```bash
   python main.py <BV号>
替换 <BV号> 为你要下载的视频 BV 号。 </br>

2. 使用演示
![1](https://github.com/user-attachments/assets/5cd99563-a747-4a60-b1ff-0cc64012f151)
