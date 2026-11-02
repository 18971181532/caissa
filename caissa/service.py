"""CLI 与网页工作台共用的门面。

两层之上的东西（终端、HTTP、测试）都只跟这个模块打交道，不直接碰
Engine 的搜索细节。这样"一次搜索"的语义只有一处定义。
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from .board import Position, START_FEN, move_uci, parse_uci
from .eval import MATE, evaluate, format_score
from .san import parse_san, to_san
from .search import Engine, Limits, SearchResult

STATUS_TEXT = {
    "playing": "进行中",
    "checkmate": "将杀",
    "stalemate": "逼和",
    "draw": "和棋",
}


def score_text(cp: int, depth: int = 0) -> str:
    if abs(cp) > MATE - 200:
        n = (MATE - abs(cp) + 1) // 2
        return ("−" if cp < 0 else "") + f"#{n}"
    return format_score(cp)


def status_of(pos: Position) -> str:
    if not pos.has_legal_move():
        return "checkmate" if pos.in_check() else "stalemate"
    if pos.halfmove >= 100 or pos.is_repetition(2) or pos.insufficient_material():
        return "draw"
    return "playing"


def pv_san(pos: Position, pv: List[int], limit: int = 12) -> List[str]:
    """把一串内部着法翻成 SAN。走完会复原。"""
    out: List[str] = []
    made: List[int] = []
    for raw in pv[:limit]:
        # PV 可能是刚由 UCI 文本转回来的，先对齐内部编码
        move = pos.resolve(raw)
        if move is None:
            break
        out.append(to_san(pos, move))
        pos.make(move)
        made.append(move)
    for move in reversed(made):
        pos.unmake(move)
    return out


class Coach:
    """带缓存的引擎外壳：一次只跑一盘分析。"""

    def __init__(self, engine: Optional[Engine] = None, megabytes: float = 32.0):
        self.engine = engine or Engine(megabytes)
        self.lock = threading.Lock()
        self.last: Optional[Dict[str, object]] = None

    # -- 局面 -------------------------------------------------------------

    def state(self, fen: str = START_FEN) -> Dict[str, object]:
        pos = Position(fen)
        detail: Dict[str, int] = {}
        cp = evaluate(pos, detail)
        legal = pos.legal_moves()
        return {
            "fen": pos.fen(),
            "turn": "w" if pos.turn == 0 else "b",
            "check": pos.in_check(),
            "status": status_of(pos),
            "status_text": STATUS_TEXT[status_of(pos)],
            "eval": cp,
            "eval_text": score_text(cp),
            "legal": [{"uci": move_uci(m), "san": to_san(pos, m, legal)} for m in legal],
            "detail": detail,
            "fullmove": pos.fullmove,
        }

    def apply(self, fen: str, move_text: str) -> Dict[str, object]:
        """走一步（UCI 或 SAN 都认），返回新局面。"""
        pos = Position(fen)
        raw = parse_uci(move_text)
        move = pos.resolve(raw) if raw is not None else None
        if move is None:
            move = parse_san(pos, move_text)
        if move is None:
            raise ValueError(f"看不懂这步棋：{move_text!r}")
        legal = pos.legal_moves()
        san = to_san(pos, move, legal)
        if not pos.make(move):
            raise ValueError(f"不合法着法：{move_text!r}")
        state = self.state(pos.fen())
        state["san"] = san
        state["uci"] = move_uci(move)
        return state

    # -- 分析 -------------------------------------------------------------

    def analyze(self, fen: str = START_FEN, depth: int = 0,
                movetime: float = 0.0, max_depth: int = 64) -> Dict[str, object]:
        """depth 与 movetime 可以同时给：先到哪个就用哪个。

        只给 depth 就一直搜到那个层数（CLI 用）；同时给 movetime 就有了
        时间上限（网页用，保证界面不会卡住）。
        """
        pos = Position(fen)
        limits = Limits(depth=max_depth if depth <= 0 else depth)
        if movetime > 0:
            limits.movetime = movetime
        elif not depth:
            limits.movetime = 0.5
        with self.lock:
            result = self.engine.search(pos, limits)
            stats = dict(self.engine.stats)
        snapshot = Position(fen)
        payload = {
            "best": move_uci(result.best_move) if result.best_move else "",
            "best_san": "",
            "score": result.score,
            "score_text": score_text(result.score, result.depth),
            "depth": result.depth,
            "seldepth": result.seldepth,
            "nodes": result.nodes,
            "qnodes": result.qnodes,
            "nps": result.nps,
            "time": result.time,
            "pv": pv_san(snapshot, result.pv),
            "lines": [],
            "stats": stats,
        }
        if result.best_move:
            legal = snapshot.legal_moves()
            payload["best_san"] = to_san(snapshot, result.best_move, legal)
        for line in result.lines[-8:]:
            payload["lines"].append({                      # type: ignore[union-attr]
                "depth": line["depth"],
                "score": line["score"],
                "score_text": score_text(int(line["score"])),
                "nodes": line["nodes"],
                "time": line["time"],
                "nps": line["nps"],
                "seldepth": line["seldepth"],
                "pv": pv_san(Position(fen), [parse_uci(u) for u in line["pv"] if parse_uci(u)]),
            })
        self.last = payload
        return payload

    def best_move(self, fen: str, depth: int = 6, movetime: float = 0.0
                  ) -> Dict[str, object]:
        return self.analyze(fen, depth=depth, movetime=movetime)


__all__ = ["Coach", "score_text", "status_of", "pv_san", "STATUS_TEXT"]
