"""终端输出的几个小工具。

Windows 上把输出重定向到管道时，Python 默认用 GBK 编码，遇到棋盘上的
Unicode 棋子会直接抛 UnicodeEncodeError。这里统一改成 UTF-8，并提供一个
"这个终端到底能不能显示宽字符"的探测。
"""

from __future__ import annotations

import os
import sys


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def supports_unicode() -> bool:
    if os.environ.get("CAISSA_ASCII"):
        return False
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if "utf" not in encoding:
        return False
    if os.name == "nt":
        # Windows Terminal / VS Code 终端都认，老 conhost 也大多认了
        return bool(os.environ.get("WT_SESSION") or os.environ.get("TERM_PROGRAM")
                    or os.environ.get("TERM") or True)
    return True


def use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"


def paint(text: str, *codes: str) -> str:
    if not use_color() or not codes:
        return text
    return "".join(codes) + text + RESET


def rule(width: int = 62, char: str = "─") -> str:
    return char * width


def display_width(text: str) -> int:
    """终端里的显示宽度：汉字算两格。"""
    import unicodedata
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def ljust(text: str, width: int, fill: str = " ") -> str:
    return text + fill * max(0, width - display_width(text))


def rjust(text: str, width: int, fill: str = " ") -> str:
    return fill * max(0, width - display_width(text)) + text


__all__ = ["force_utf8", "supports_unicode", "use_color", "paint", "rule",
           "display_width", "ljust", "rjust", "RESET", "DIM", "BOLD", "RED",
           "GREEN", "YELLOW", "BLUE", "CYAN"]
