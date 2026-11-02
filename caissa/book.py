"""开局库。

不是 polyglot 那种二进制库，就是十几条主流行棋路线，编译成
"局面指纹 → 候选着法"。开局阶段直接照着走，省下思考时间，也让每局的
开局不至于千篇一律。

库里没有的局面就正常搜索——所以它只是个提速的小配件，不是必需品。
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .board import Position
from .san import parse_san

#: 每条线是一串 SAN。选的都是主线，走到第 8-10 回合为止。
LINES: Tuple[str, ...] = (
    # 西班牙
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O",
    "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4 d4 Nd6 Bxc6 dxc6 dxe5 Nf5",
    # 意大利
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d4 exd4 cxd4 Bb4+",
    "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Bc5 c3 d6 O-O O-O",
    # 苏格兰
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nc3 Bb4 Nxc6 bxc6",
    # 西西里
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5",
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 g6 Nc3 Bg7 Be3 Nf6",
    "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6 Nc3 Qc7",
    # 法兰西 / 卡罗康
    "e4 e6 d4 d5 Nc3 Nf6 e5 Nfd7 f4 c5",
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6",
    # 双马 / 俄罗斯
    "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5",
    # 后翼弃兵 / 尼姆佐 / 王印度
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O",
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O",
    # 英国式 / 列蒂
    "c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5 Bg2 Nb6",
    "Nf3 d5 g3 Nf6 Bg2 g6 O-O Bg7 d3 O-O",
    # 斯堪的纳维亚
    "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6",
)


class OpeningBook:
    def __init__(self, lines: Tuple[str, ...] = LINES, seed: int = 20261031):
        self.lines = lines
        self.random = random.Random(seed)
        self._book: Optional[Dict[int, List[int]]] = None

    def _build(self) -> Dict[int, List[int]]:
        book: Dict[int, List[int]] = {}
        for line in self.lines:
            pos = Position()
            for token in line.split():
                move = parse_san(pos, token)
                if move is None:
                    break
                book.setdefault(pos.key, []).append(move)
                if not pos.make(move):
                    break
        return book

    @property
    def book(self) -> Dict[int, List[int]]:
        if self._book is None:
            self._book = self._build()
        return self._book

    def pick(self, pos: Position) -> Optional[int]:
        moves = self.book.get(pos.key)
        if not moves:
            return None
        # 同一局面可能有几条线经过，随机挑一条让对局有变化
        return self.random.choice(moves)

    def __len__(self) -> int:
        return len(self.book)


__all__ = ["OpeningBook", "LINES"]
