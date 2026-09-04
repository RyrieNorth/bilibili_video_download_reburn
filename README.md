# bilibili_video_download_reburn

一个简单的用于下载 Bilibili 视频的 Python 工具，支持单P与多P视频下载 </br>
API库已于`2026年1月28日`停止维护并删除相关文档及源代码。

自 `v0.3` 版本开始已将 `windows` 与 `linux` 版本区分</br>
`v0.4`版本新增番剧下载功能</br>
`v0.5`版本引入新的rich库优化了交互逻辑，且不再区分`windows`与`linux`。</br>
`v0.6`版本新增仅下载视频或音频功能，音频默认格式为m4a。

## 功能

- 支持单P与多P视频下载
- 支持视频和音频分开下载
- 自动选择视频质量
- 合并视频和音频为 MP4 格式

## 环境要求

- Python 3.13 或更高版本
- `requests`, `qrcode`, windows 还会需要`PyQt5, PyQt5-tools` 库（已于`0.3`版移除）
- `Aria2c` 工具（用于下载视频）（已集成在tools文件夹中）
- `FFmpeg` 工具（用于合并视频和音频）（已集成在tools文件夹中且已经过裁剪）

## 安装方式

1. 克隆安装：
   ```bash
   git clone https://github.com/RyrieNorth/bilibili_video_download_reburn.git
   cd bilibili_video_download_reburn/
   uv pip install -e .

2. 从release中下载安装：
   ```bash
   wget https://github.com/RyrieNorth/bilibili_video_download_reburn/releases/download/v0.5/bilibili_video_download_reburn-0.5.0-py3-none-any.whl
   uv pip/pip install bilibili_video_download_reburn_for_windows-0.5-py3-none-any.whl

3. 如何卸载：
   ```bash
   uv pip/pip list # 查找bilibili_video_download相关字眼, 例如：bilibili-video-download-reburn-for-windows
   uv pip/pip uninstall bilibili-video-download-reburn-for-windows

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
       "video_info": "https://api.bilibili.com/x/web-interface/view",   //查询视频详细信息
       "get_anime": "https://api.bilibili.com/pgc/view/web/season"   //解析番剧bvid
     },
     "basic_headers": {
       "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", //补全UA
       "referer": "https://www.bilibili.com"   //b站视频的防盗链，勿删，否则视频会无法下载
     },
     "network": {
       "connect_timeout": 5,   //网络连接超时
       "read_timeout": 15,   //文件读取超时
       "retries": 3,   //重试次数
       "backoff_factor": 0.5   //控制重试延迟
     },
     "download": {
       "output_dir": "video",   //视频输出路径，默认当前项目的路径，请指定 -o 参数
       "concurrent_downloads": 3,   //并行下载数，默认三个请求，不建议太高，避免触发风控
       "mux_workers": 2   //合并队列线程数，默认两个。
     },
     "aria2c": {
       "split": "8",   //分片下载，这里设置8片，最大可设32，过大的会话可能会被服务器限流
       "max_connection_per_server": "2"   //服务器最大连接数，某些地方的网络可能会限制会话，若出现视频下载未响应请调整，默认为2
       "rpc_port": 0,   //RPC端口，0.5版本启用Aria2c的jsonRPC模式，故需要额外配置
       "startup_timeout": 10,   //启动超时时长
       "poll_interval": 0.4,   //队列查询时间
       "extra_args": []   //额外参数
     }
   }

## 使用方式

1. 在终端直接运行：
   ```bash
   bilidl <BV号/番剧号> 
替换 <BV号> 为你要下载的视频 BV/番剧 号。(期间若没有登陆成功会触发登陆逻辑) </br>

2. 作为库使用：
   ```python
   from bilidl.inferface import download
   video_id = "BV1Gg411L7zg"
   download(video_id)

   from bilidl.inferface import download
   video_id = "ep1349841"
   download(video_id)

3. 使用演示</br>
**当cookies信息不存在时：**</br></br>
![show_1](https://github.com/user-attachments/assets/4568d8c7-7ad1-4213-a129-71282cc8dd58)
</br>

**0.5版本演示：**</br></br>
<img width="730" height="357" alt="image" src="https://github.com/user-attachments/assets/0a1fa20d-79e6-44a4-ae9c-aef1131beebe" />


**命令行演示（旧版）：**</br></br>
![show_2](https://github.com/user-attachments/assets/88291763-ef42-45e7-91bc-22171419b9f9)

**作为库调用运行：**</br></br>
![show_3](https://github.com/user-attachments/assets/ed88477e-583a-4c0a-8522-d028b69b3be8)

**单P模式(旧版)：**</br>
![1](https://github.com/user-attachments/assets/5cd99563-a747-4a60-b1ff-0cc64012f151)

**多P模式(旧版)：**</br>
![1](https://github.com/user-attachments/assets/e8056adf-98b1-4017-9d76-d55f1a6a773e)

**视频信息：**</br>
![image](https://github.com/user-attachments/assets/bed74c2c-4a37-4f79-baff-be533f2d590e)

## 关于字符集</br>
1. 由于我当前环境下的Windows10 CMD代码页为GBK(936), 字体为新宋体, 这样会导致二维码显示异常, 如下图：
![qr_err](https://github.com/user-attachments/assets/899394cc-c728-493f-b8bd-9f4a96f69e85)
2. 解决方式为, 修改CMD代码页与字体, 如下图：
![zifu](https://github.com/user-attachments/assets/34c81b41-5fad-496f-afe1-fcf858e122d5)
![ziti](https://github.com/user-attachments/assets/79b29cb6-ea7c-404c-b6f2-f007ceb3a165)
3. Windows11无需执行上述步骤。


## 须知
1. 非登录用户只能下载360P视频
2. 非大会员用户只能下载低码率1080P视频
3. 目前发现低分辨率视频，例如360p会下载失败，后续会修正（已解决）
4. 1080P+，1080P60，4k，8k，杜比，Hi-Res等视频需要账号性质为大会员方得下载

## 已知问题（已于0.5版本解决）
1. 在Linux下使用时无法正常显示进度条(测试环境：CentOS 7.9 2009、RockyLinux 9.3), 故推荐使用Windows平台运行本工具
