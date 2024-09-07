import os
import subprocess
import re
import sys

class Aria2c:
    def __init__(self, download_path, referer, aria2c_config):
        self.download_path = download_path
        self.referer = referer
        self.aria2c = self.get_aria2c_command()
        self.aria2c_config = aria2c_config

    def get_aria2c_command(self):
        aria2c_path = r".\tools\aria2c.exe" if os.name == "nt" else "./tools/aria2c"
        if not os.path.isfile(aria2c_path):
            raise FileNotFoundError(f"指定的工具文件 {aria2c_path} 不存在，请检查路径。")
        return aria2c_path

    def aria2c_options(self):
        options = [
            "-c" if self.aria2c_config.get("continue") == "true" else "",
            f'-s{self.aria2c_config.get("split", 1)}' if "split" in self.aria2c_config else "",
            f'-x{self.aria2c_config.get("max_connection_per_server", 1)}' if "max_connection_per_server" in self.aria2c_config else "",
            "--file-allocation=none",
            "--summary-interval=0"
        ]
        return " ".join(filter(None, options))

    def print_progress_bar(self, progress, total, bar_length=40):
        percent = float(progress) / total
        arrow = '█' * int(round(percent * bar_length))
        spaces = ' ' * (bar_length - len(arrow))
        sys.stdout.write(f"\rProgress: [{arrow}{spaces}] {progress}%")
        sys.stdout.flush()

    def run_download_command(self, url, output_file):
        output_path = os.path.join(self.download_path, output_file)
        aria2c_options = self.aria2c_options()
        download_command = f'{self.aria2c} {aria2c_options} --referer="{self.referer}" "{url}" -o "{output_path}"'

        with subprocess.Popen(
            download_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, universal_newlines=True, encoding="utf-8"
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
        ffmpeg_path = r".\tools\ffmpeg.exe" if os.name == "nt" else "./tools/ffmpeg"
        if not os.path.isfile(ffmpeg_path):
            raise FileNotFoundError(f"指定的工具文件 {ffmpeg_path} 不存在，请检查路径。")
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
