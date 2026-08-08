#!/usr/bin/env python
import sys
from pathlib import Path

# 直接以脚本方式运行时，确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bilidl.cli import run  # noqa: E402

if __name__ == "__main__":
    run()
