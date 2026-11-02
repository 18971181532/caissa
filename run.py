#!/usr/bin/env python3
"""不用安装也能跑的入口。

    python run.py play
    python run.py search --depth 8
    python run.py serve
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from caissa.cli import main

if __name__ == "__main__":
    sys.exit(main())
