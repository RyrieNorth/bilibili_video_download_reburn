from setuptools import setup
import os
import stat
import platform
from setuptools.command.install import install


# 添加执行权限的函数
def add_execute_permission_to_directory(directory):
    """给目录中的所有文件添加执行权限"""
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)

            # 如果是 Linux 系统，添加执行权限
            if platform.system() == "Linux":
                st = os.stat(file_path)
                os.chmod(file_path, st.st_mode | stat.S_IEXEC)
            else:
                pass


# 自定义安装命令类
class CustomInstallCommand(install):
    def run(self):
        # 调用默认的安装过程
        install.run(self)

        # 如果是 Linux 系统，给 ./tools 目录下的文件添加执行权限
        if platform.system() == "Linux":
            add_execute_permission_to_directory("./tools")
        else:
            pass


setup(
    name="bilibili_video_download_reburn",
    version="0.2",
    description="A tool for downloading and processing Bilibili videos",
    author="RyrieNorth",
    author_email="bk15018708480@gmail.com",
    install_requires=[
        "requests",
        "qrcode",
    ],
    extras_require={
        "windows": ["PyQt5", "PyQt5-tools"],
        "linux": [],
    },
    py_modules=["main", "tools_wrapper", "utils"],
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    cmdclass={
        "install": CustomInstallCommand,  # 使用自定义的安装命令
    },
)
