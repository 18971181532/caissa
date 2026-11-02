"""Caissa —— 零依赖的国际象棋引擎。

位板走子生成、α-β 搜索、UCI 协议与网页工作台，只用 Python 标准库。
"""

from .board import Position, START_FEN, move_uci, parse_uci
from .eval import evaluate, format_score
from .search import Engine, Limits, SearchResult
from .san import Game, parse_pgn, parse_san, to_san
from .service import Coach

__version__ = "1.0.0"

__all__ = ["Position", "START_FEN", "move_uci", "parse_uci", "evaluate",
           "format_score", "Engine", "Limits", "SearchResult", "Game",
           "parse_pgn", "parse_san", "to_san", "Coach", "__version__"]
