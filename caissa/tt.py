"""置换表。

同一局面可以从不同着法顺序走到。把它已经算过的分数记下来，第二次遇到
就直接用——搜索树是棵树，但它的"局面图"要小得多。

条目里存四样东西：深度、分数、边界类型、最佳着法。边界类型决定这个分数
能不能直接用：精确值可以闭眼用，下界只能用来提高 alpha，上界只能用来压
beta。用错了会剪掉真正的解。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

EXACT, LOWER, UPPER = 0, 1, 2


class TranspositionTable:
    __slots__ = ("data", "limit", "hits", "probes", "cutoffs", "stores")

    def __init__(self, megabytes: float = 32.0):
        # 一个条目在 Python 里远不止 16 字节，这里按"多少条"来限，
        # 用 MB 数折算成一个保守的条数，避免把内存吃光。
        self.limit = max(1024, int(megabytes * 1024 * 1024 / 120))
        self.data: Dict[int, Tuple[int, int, int, int]] = {}
        self.hits = 0
        self.probes = 0
        self.cutoffs = 0
        self.stores = 0

    def clear(self) -> None:
        self.data.clear()
        self.hits = self.probes = self.cutoffs = self.stores = 0

    def probe(self, key: int) -> Optional[Tuple[int, int, int, int]]:
        self.probes += 1
        entry = self.data.get(key)
        if entry is not None:
            self.hits += 1
        return entry

    def store(self, key: int, depth: int, score: int, flag: int, move: int) -> None:
        if len(self.data) >= self.limit:
            # 简单的"半清"策略：整表清空会让搜索质量抖动一下，
            # 但比维护一个 LRU 便宜得多，也够用。
            self.data.clear()
        old = self.data.get(key)
        if old is not None and old[0] > depth and old[3]:
            return
        self.data[key] = (depth, score, flag, move)
        self.stores += 1

    @property
    def fill(self) -> float:
        return len(self.data) / self.limit if self.limit else 0.0

    def __len__(self) -> int:
        return len(self.data)


__all__ = ["TranspositionTable", "EXACT", "LOWER", "UPPER"]
