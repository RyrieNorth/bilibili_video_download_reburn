from setuptools import setup

setup(
    name='bilibili_video_download_reburn',
    version='0.1',
    description='A tool for downloading and processing Bilibili videos',
    author='NorthSky-Ryrie',
    author_email='2586649501@qq.com',
    install_requires=[
        'requests',
        'qrcode',
    ],
    extras_require={
        'windows': ['PyQt5', 'PyQt5-tools'],
        'linux': [],
    },
    py_modules=['main', 'tools_wrapper', 'utils'],
    include_package_data=True,
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
