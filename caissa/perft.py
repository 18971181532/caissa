"""perft：把整棵着法树数到底，统计叶子个数。

这是棋规实现的唯一硬指标。走子、吃子、易位、吃过路兵、升变、将军回避，
任何一处写错，数字立刻对不上。业界有公认的标准数字可以逐层核对。
"""

from __future__ import annotations

import time
from typing import Dict, List, Tuple

from .board import Position, move_uci

#: 六个标准测试局面的 perft 参考值（从深度 1 开始）。
SUITE: Dict[str, Tuple[str, Tuple[int, ...]]] = {
    "startpos": (
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        (20, 400, 8902, 197281, 4865609, 119060324),
    ),
    "kiwipete": (
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        (48, 2039, 97862, 4085603, 193690690),
    ),
    "position3": (
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        (14, 191, 2812, 43238, 674624, 11030083),
    ),
    "position4": (
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        (6, 264, 9467, 422333, 15833292),
    ),
    "position5": (
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        (44, 1486, 62379, 2103487, 89941194),
    ),
    "position6": (
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        (46, 2079, 89890, 3894594, 164075551),
    ),
}


def perft(pos: Position, depth: int) -> int:
    """深度优先数叶子。depth = 0 时返回 1（自己就是一个叶子）。"""
    if depth <= 0:
        return 1
    total = 0
    for move in pos.generate_moves():
        if pos.make(move):
            total += perft(pos, depth - 1)
            pos.unmake(move)
    return total


def perft_divide(pos: Position, depth: int) -> List[Tuple[str, int]]:
    """按第一步分组，用来定位哪一步的子树数目不对。"""
    out = []
    for move in pos.generate_moves():
        if pos.make(move):
            out.append((move_uci(move), perft(pos, depth - 1)))
            pos.unmake(move)
    out.sort(key=lambda kv: -kv[1])
    return out


def perft_timed(pos: Position, depth: int) -> Tuple[int, float]:
    t0 = time.perf_counter()
    nodes = perft(pos, depth)
    return nodes, time.perf_counter() - t0


def verify(suite=None, max_depth: int = 4, progress=None) -> List[Dict[str, object]]:
    """跑标准套件，返回每个局面的核对结果。"""
    suite = suite or SUITE
    results = []
    for name, (fen, expected) in suite.items():
        pos = Position(fen)
        depth = min(max_depth, len(expected))
        got, elapsed = perft_timed(pos, depth)
        want = expected[depth - 1]
        results.append({
            "name": name, "depth": depth, "got": got, "want": want,
            "ok": got == want, "seconds": elapsed,
            "nps": got / elapsed if elapsed else 0.0,
        })
        if progress:
            progress(results[-1])
    return results


__all__ = ["SUITE", "perft", "perft_divide", "perft_timed", "verify"]
