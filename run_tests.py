#!/usr/bin/env python3
"""跑全部测试。

    python run_tests.py
    python run_tests.py -v
    python run_tests.py tests.test_board

不依赖 pytest：unittest 是标准库的一部分，装 Python 就能跑。
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from caissa.console import force_utf8  # noqa: E402


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force_utf8()
    verbosity = 1
    if "-v" in argv or "--verbose" in argv:
        verbosity = 2
        argv = [a for a in argv if a not in ("-v", "--verbose")]

    loader = unittest.TestLoader()
    if argv and not argv[0].startswith("-"):
        names = ["tests." + a if not a.startswith("tests.") else a for a in argv]
        suite = loader.loadTestsFromNames(names)
    else:
        suite = loader.discover(os.path.join(ROOT, "tests"), top_level_dir=ROOT)

    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
