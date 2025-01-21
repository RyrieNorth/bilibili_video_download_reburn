#!/usr/bin/env python
import os
import subprocess
import re
import sys
import platform
import stat
from pathlib import Path

# 获取当前脚本的目录路径
current_dir = Path(__file__).resolve().parent


# 给文件添加执行权限
def add_execute_permission(file_path):
    """给文件添加执行权限（Linux系统）"""
    if platform.system() == "Linux":
        # 获取当前文件的权限，并添加执行权限
        st = os.stat(file_path)
        os.chmod(file_path, st.st_mode | stat.S_IEXEC)
    else:
        pass


# 获取当前脚本的目录路径
current_dir = Path(__file__).resolve().parent

# 根据操作系统设置 aria2c 和 ffmpeg 的路径
aria2c_path = current_dir.joinpath(
    "tools", "aria2c.exe" if os.name == "nt" else "aria2c"
)
ffmpeg_path = current_dir.joinpath(
    "tools", "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
)

# 添加执行权限（仅适用于 Linux）
add_execute_permission(aria2c_path)
add_execute_permission(ffmpeg_path)


class Aria2c:
    def __init__(self, download_path, referer, aria2c_config):
        self.download_path = download_path
        self.referer = referer
        self.aria2c = self.get_aria2c_command()
        self.aria2c_config = aria2c_config

    def get_aria2c_command(self):
        # 根据操作系统选择aria2c路径
        if not os.path.isfile(aria2c_path):
            raise FileNotFoundError(
                f"指定工具文件 {aria2c_path} 不存在, 请检查路径或该工具是否存在。"
            )
        return aria2c_path

    def aria2c_options(self):
        options = [
            "-c" if self.aria2c_config.get("continue") == "true" else "",
            (
                f'-s{self.aria2c_config.get("split", 1)}'
                if "split" in self.aria2c_config
                else ""
            ),
            (
                f'-x{self.aria2c_config.get("max_connection_per_server", 1)}'
                if "max_connection_per_server" in self.aria2c_config
                else ""
            ),
            "--file-allocation=none",
            "--check-certificate=false",  # aria2c编译时使用非RHEL的发行版, 故在建立SSL/TLS连接时会提示找不到CA证书, 故这里直接关闭证书校验
            "--summary-interval=0",
        ]
        return " ".join(filter(None, options))

    def print_progress_bar(self, progress, total, bar_length=40):
        percent = float(progress) / total
        arrow = "█" * int(round(percent * bar_length))
        spaces = " " * (bar_length - len(arrow))
        sys.stdout.write(f"\rProgress: [{arrow}{spaces} ] {progress}%")
        sys.stdout.flush()

    def run_download_command(self, url, output_file):
        output_path = os.path.join(self.download_path, output_file)
        aria2c_options = self.aria2c_options()
        download_command = f'{self.aria2c} {aria2c_options} --referer="{self.referer}" "{url}" -o "{output_path}"'

        with subprocess.Popen(
            download_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            universal_newlines=True,
            encoding="utf-8",
        ) as process:
            total_progress = 100

            for output in process.stdout:
                progress = self.parse_progress(output)
                if progress is not None:
                    self.print_progress_bar(progress, total_progress)

            process.wait()

        sys.stdout.write("\nDownload Completed.\n")
        sys.stdout.flush()
        return process.returncode

    def parse_progress(self, output):
        match = re.search(r"\((\d+)%\)", output)
        return int(match.group(1)) if match else None

    def download_video(self, video_title, video_url):
        return self.run_download_command(video_url, f"{video_title}.m4s")

    def download_audio(self, video_title, audio_url):
        return self.run_download_command(audio_url, f"{video_title}_audio.m4s")


class FFmpeg:
    def __init__(self, video_path):
        self.video_path = video_path
        self.ffmpeg = self.get_ffmpeg_command()

    def get_ffmpeg_command(self):
        if not os.path.isfile(ffmpeg_path):
            raise FileNotFoundError(
                f"指定工具文件 {ffmpeg_path} 不存在, 请检查路径或该工具是否存在。"
            )
        return ffmpeg_path

    def run_ffmpeg_command(self, video_title):
        video_input_path = os.path.join(self.video_path, f"{video_title}.m4s")
        audio_input_path = os.path.join(self.video_path, f"{video_title}_audio.m4s")
        output_path = os.path.join(self.video_path, f"{video_title}.mp4")

        ffmpeg_command = (
            f'{self.ffmpeg} -y -i "{video_input_path}" -i "{audio_input_path}" '
            "-vcodec copy -acodec copy "
            f'"{output_path}"'
        )

        with subprocess.Popen(
            ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        ) as ffmpeg_process:
            stdout, stderr = ffmpeg_process.communicate()

        return ffmpeg_process.returncode, stdout, stderr
