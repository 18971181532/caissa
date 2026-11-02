"""搜索。

主搜索是负极大值形式的 α-β（PVS），外面套一层迭代加深。真正让它能下棋的
是这些剪枝：

* 置换表：同一局面只算一次
* 空着剪枝：白送一步对方都占不到便宜，那这里不必细算
* 后期着法削减（LMR）：排在后面的安静着法先用浅一层搜，有价值再重搜
* 静态搜索：只吃子的着法不算完，否则 horizons effect 会让引擎自杀
* 杀手着法 + 历史启发：把"上次在这里砍出剪枝的着法"排到前面

所有分数都是"轮到走棋的一方"的视角，将杀用 ±32000 附近的绝对值表示，
离根越近的将杀分越高（这样引擎会挑最快的杀法）。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .board import (
    FLAG_CAPTURE, Position, VALUE, move_from, move_flags, move_promo, move_to,
    move_uci,
)
from .eval import INF, MATE, evaluate
from .tt import EXACT, LOWER, UPPER, TranspositionTable

sys.setrecursionlimit(8000)

MAX_PLY = 96
MATE_THRESHOLD = MATE - 200


class SearchAbort(Exception):
    """超时或被要求停下。只在 search() 里被捕获。"""


@dataclass
class Limits:
    depth: int = 64
    movetime: float = 0.0          # 秒
    nodes: int = 0
    wtime: float = 0.0
    btime: float = 0.0
    winc: float = 0.0
    binc: float = 0.0
    movestogo: int = 0

    @classmethod
    def from_uci(cls, tokens: Dict[str, str]) -> "Limits":
        def num(name, default=0.0):
            try:
                return float(tokens.get(name, default))
            except (TypeError, ValueError):
                return default
        return cls(
            depth=int(num("depth", 64)) or 64,
            movetime=num("movetime") / 1000.0,
            nodes=int(num("nodes", 0)),
            wtime=num("wtime") / 1000.0,
            btime=num("btime") / 1000.0,
            winc=num("winc") / 1000.0,
            binc=num("binc") / 1000.0,
            movestogo=int(num("movestogo", 0)),
        )


@dataclass
class SearchResult:
    best_move: int = 0
    score: int = 0
    depth: int = 0
    pv: List[int] = field(default_factory=list)
    nodes: int = 0
    qnodes: int = 0
    time: float = 0.0
    seldepth: int = 0
    lines: List[Dict[str, object]] = field(default_factory=list)

    @property
    def nps(self) -> float:
        return self.nodes / self.time if self.time > 0 else 0.0

    @property
    def pv_uci(self) -> List[str]:
        return [move_uci(m) for m in self.pv]


def allocate_time(limits: Limits, turn: int) -> float:
    """把剩余时间切一块给这一步。"""
    if limits.movetime > 0:
        return limits.movetime
    if limits.nodes:
        return 0.0
    remaining = limits.wtime if turn == 0 else limits.btime
    inc = limits.winc if turn == 0 else limits.binc
    if remaining <= 0:
        return 0.0
    moves = limits.movestogo or 30
    budget = remaining / moves + inc * 0.8
    # 永远留一点余量给通信与收尾
    return max(0.02, min(budget, remaining * 0.8))


class Engine:
    def __init__(self, megabytes: float = 32.0):
        self.tt = TranspositionTable(megabytes)
        self.nodes = 0
        self.qnodes = 0
        self.seldepth = 0
        self.start = 0.0
        self.deadline: Optional[float] = None
        self.node_limit = 0
        self.stop = False
        self.root_move = 0
        self.prev_score: Optional[int] = None
        self.killers = [[0, 0] for _ in range(MAX_PLY + 2)]
        self.history = [0] * (64 * 64)
        self.stats: Dict[str, int] = {}
        self.on_depth = None

    # -- 外部接口 ---------------------------------------------------------

    def new_game(self) -> None:
        self.tt.clear()
        self.killers = [[0, 0] for _ in range(MAX_PLY + 2)]
        self.history = [0] * (64 * 64)
        self.prev_score = None

    def search(self, pos: Position, limits: Optional[Limits] = None,
               on_depth=None) -> SearchResult:
        limits = limits or Limits()
        # 搜索会大量 make/unmake；超时中断时可能来不及全部撤销，
        # 所以在副本上干活，调用者的局面永远不受影响。
        pos = pos.clone()
        self.nodes = self.qnodes = 0
        self.seldepth = 0
        self.start = time.perf_counter()
        budget = allocate_time(limits, pos.turn)
        self.deadline = (self.start + budget) if budget > 0 else None
        self.node_limit = limits.nodes
        self.stop = False
        self.prev_score = None
        self.root_move = 0
        self.stats = {"tt_cutoff": 0, "null_cutoff": 0, "lmr": 0,
                      "lmr_research": 0, "beta_cutoff": 0, "qnode": 0}
        for i in range(0, 64 * 64, 8):        # 历史表老化
            self.history[i] >>= 1

        best = SearchResult()
        max_depth = max(1, limits.depth)
        for depth in range(1, max_depth + 1):
            try:
                score = self._aspiration(pos, depth)
            except SearchAbort:
                break
            pv = self._extract_pv(pos)
            elapsed = time.perf_counter() - self.start
            best = SearchResult(
                best_move=self.root_move, score=score, depth=depth, pv=pv,
                nodes=self.nodes, qnodes=self.qnodes, time=elapsed,
                seldepth=self.seldepth, lines=list(best.lines),
            )
            best.lines.append({
                "depth": depth, "score": score, "nodes": self.nodes,
                "time": elapsed, "seldepth": self.seldepth,
                "pv": [move_uci(m) for m in pv],
                "nps": self.nodes / elapsed if elapsed else 0.0,
            })
            self.prev_score = score
            if on_depth is not None:
                on_depth(best.lines[-1])
            if abs(score) > MATE_THRESHOLD and MATE - abs(score) <= depth:
                break                      # 已经找到最短的杀，再搜也不会更短
            if self.deadline and time.perf_counter() - self.start > budget * 0.55:
                break

        if best.best_move == 0:
            # 一层都没搜完（时间给得太少）：至少给个合法着法
            for move in pos.generate_moves():
                if pos.make(move):
                    pos.unmake(move)
                    best.best_move = move
                    break
        best.time = time.perf_counter() - self.start
        best.nodes = self.nodes
        best.qnodes = self.qnodes
        return best

    # -- 迭代加深与渴望窗口 ------------------------------------------------

    def _aspiration(self, pos: Position, depth: int) -> int:
        if self.prev_score is None or depth <= 2:
            return self._root(pos, depth, -INF, INF)
        delta = 22
        alpha = max(-INF, self.prev_score - delta)
        beta = min(INF, self.prev_score + delta)
        for _ in range(8):
            score = self._root(pos, depth, alpha, beta)
            if score <= alpha:
                alpha = max(-INF, alpha - delta * 3)
                delta *= 3
            elif score >= beta:
                beta = min(INF, beta + delta * 3)
                delta *= 3
            else:
                return score
        return self._root(pos, depth, -INF, INF)

    def _root(self, pos: Position, depth: int, alpha: int, beta: int) -> int:
        self.nodes += 1
        moves = pos.generate_moves()
        if not moves:
            return -MATE if pos.in_check() else 0
        moves = self._order(pos, moves, self.root_move, 0)
        best_score = -INF
        best_move = 0
        legal = 0
        alpha_orig = alpha
        for move in moves:
            if not pos.make(move):
                continue
            legal += 1
            if legal == 1:
                score = -self._search(pos, depth - 1, -beta, -alpha, 1)
            else:
                score = -self._search(pos, depth - 1, -alpha - 1, -alpha, 1)
                if alpha < score < beta:
                    score = -self._search(pos, depth - 1, -beta, -alpha, 1)
            pos.unmake(move)
            if score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    alpha = score
            if alpha >= beta:
                self.stats["beta_cutoff"] += 1
                break
        if legal == 0:
            return -MATE if pos.in_check() else 0
        self.root_move = best_move
        self.tt.store(pos.key, depth, self._to_tt(best_score, 0),
                      EXACT if alpha_orig < best_score < beta else
                      (LOWER if best_score >= beta else UPPER), best_move)
        return best_score

    # -- 主搜索 -----------------------------------------------------------

    def _search(self, pos: Position, depth: int, alpha: int, beta: int,
                ply: int) -> int:
        if ply > MAX_PLY:
            return evaluate(pos)
        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._tick()
        if ply > self.seldepth:
            self.seldepth = ply

        in_check = pos.in_check()
        if in_check:
            depth += 1                     # 将军延伸：被将的局面必须看下去
        if depth <= 0:
            return self._quiesce(pos, alpha, beta, ply)

        if ply > 0:
            if pos.halfmove >= 100 or pos.is_repetition(1):
                return 0

        alpha_orig = alpha
        tt_move = 0
        entry = self.tt.probe(pos.key)
        if entry is not None:
            tdepth, tscore, tflag, tmove = entry
            tt_move = tmove
            score = self._from_tt(tscore, ply)
            if tdepth >= depth and ply > 0:
                if tflag == EXACT:
                    self.stats["tt_cutoff"] += 1
                    return score
                if tflag == LOWER and score >= beta:
                    self.stats["tt_cutoff"] += 1
                    return score
                if tflag == UPPER and score <= alpha:
                    self.stats["tt_cutoff"] += 1
                    return score

        # 空着剪枝。将局面下不能用，纯兵残局不能用（那是楚克旺）。
        if (not in_check and depth >= 3 and ply > 0 and beta < MATE_THRESHOLD
                and not self._bare_pawns(pos)):
            static = evaluate(pos)
            if static >= beta:
                pos.null_move()
                reduction = 2 + depth // 4
                score = -self._search(pos, depth - 1 - reduction,
                                      -beta, -beta + 1, ply + 1)
                pos.unmake_null()
                if score >= beta:
                    self.stats["null_cutoff"] += 1
                    return beta if score < MATE_THRESHOLD else score

        moves = pos.generate_moves()
        moves = self._order(pos, moves, tt_move, ply)

        best_score = -INF
        best_move = 0
        legal = 0
        for index, move in enumerate(moves):
            if not pos.make(move):
                continue
            legal += 1
            gives_check = pos.in_check()
            quiet = not (move_flags(move) & FLAG_CAPTURE) and not move_promo(move)

            if legal == 1:
                score = -self._search(pos, depth - 1, -beta, -alpha, ply + 1)
            else:
                reduction = 0
                if (quiet and not gives_check and not in_check
                        and depth >= 3 and index >= 3):
                    reduction = 1 + (index >= 6) + (depth >= 6) + (index >= 12)
                    if reduction > depth - 2:
                        reduction = depth - 2
                if reduction:
                    self.stats["lmr"] += 1
                    score = -self._search(pos, depth - 1 - reduction,
                                          -alpha - 1, -alpha, ply + 1)
                    if score > alpha:
                        self.stats["lmr_research"] += 1
                        score = -self._search(pos, depth - 1, -alpha - 1,
                                              -alpha, ply + 1)
                else:
                    score = -self._search(pos, depth - 1, -alpha - 1, -alpha,
                                          ply + 1)
                if alpha < score < beta:
                    score = -self._search(pos, depth - 1, -beta, -alpha,
                                          ply + 1)
            pos.unmake(move)

            if score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    alpha = score
                    if quiet:
                        self.history[(move_from(move) << 6) | move_to(move)] += depth * depth
            if alpha >= beta:
                self.stats["beta_cutoff"] += 1
                if quiet:
                    slot = self.killers[ply]
                    if slot[0] != move:
                        slot[1] = slot[0]
                        slot[0] = move
                break

        if legal == 0:
            return -MATE + ply if in_check else 0

        flag = EXACT
        if best_score <= alpha_orig:
            flag = UPPER
        elif best_score >= beta:
            flag = LOWER
        self.tt.store(pos.key, depth, self._to_tt(best_score, ply), flag, best_move)
        return best_score

    # -- 静态搜索 ---------------------------------------------------------

    def _quiesce(self, pos: Position, alpha: int, beta: int, ply: int) -> int:
        self.qnodes += 1
        self.stats["qnode"] += 1
        if (self.qnodes & 1023) == 0:
            self._tick()
        if ply > MAX_PLY:
            return evaluate(pos)

        stand = evaluate(pos)
        if stand >= beta:
            return stand
        if stand > alpha:
            alpha = stand

        moves = pos.generate_moves(captures=True)
        scored = []
        board = pos.board
        for move in moves:
            victim = board[move_to(move)] & 7
            attacker = board[move_from(move)] & 7
            gain = VALUE[victim] if victim else VALUE[move_promo(move)]
            scored.append((gain * 16 - VALUE[attacker], move))
        scored.sort(key=lambda kv: -kv[0])

        for gain, move in scored:
            # delta 剪枝：就算白吃这个子也追不上 alpha，就别看了
            if stand + gain < alpha - 120:
                continue
            if not pos.make(move):
                continue
            score = -self._quiesce(pos, -beta, -alpha, ply + 1)
            pos.unmake(move)
            if score >= beta:
                return score
            if score > alpha:
                alpha = score
        return alpha

    # -- 辅助 -------------------------------------------------------------

    def _tick(self) -> None:
        if self.stop:
            raise SearchAbort
        if self.node_limit and self.nodes >= self.node_limit:
            raise SearchAbort
        if self.deadline is not None and time.perf_counter() >= self.deadline:
            raise SearchAbort

    def _bare_pawns(self, pos: Position) -> bool:
        """只剩兵和王——这种局面里"白送一步"可能反而是好事，不能剪。"""
        for color in (0, 1):
            base = color << 3
            if (pos.bb[base | 2] or pos.bb[base | 3]
                    or pos.bb[base | 4] or pos.bb[base | 5]):
                return False
        return True

    def _to_tt(self, score: int, ply: int) -> int:
        if score > MATE_THRESHOLD:
            return score + ply
        if score < -MATE_THRESHOLD:
            return score - ply
        return score

    def _from_tt(self, score: int, ply: int) -> int:
        if score > MATE_THRESHOLD:
            return score - ply
        if score < -MATE_THRESHOLD:
            return score + ply
        return score

    def _order(self, pos: Position, moves: List[int], tt_move: int,
               ply: int) -> List[int]:
        killers = self.killers[ply] if ply < len(self.killers) else (0, 0)
        history = self.history
        board = pos.board
        scored = []
        for move in moves:
            if move == tt_move and tt_move:
                key = 1 << 26
            elif move_flags(move) & FLAG_CAPTURE or move_promo(move):
                victim = board[move_to(move)] & 7
                attacker = board[move_from(move)] & 7
                gain = VALUE[victim] if victim else VALUE[move_promo(move)]
                key = (1 << 22) + gain * 16 - VALUE[attacker]
            elif move == killers[0]:
                key = 1 << 21
            elif move == killers[1]:
                key = 1 << 20
            else:
                key = history[(move_from(move) << 6) | move_to(move)]
            scored.append((key, move))
        scored.sort(key=lambda kv: -kv[0])
        return [move for _, move in scored]

    def _extract_pv(self, pos: Position, limit: int = 20) -> List[int]:
        """沿着置换表里的最佳着法一路走下去，就是主变。"""
        pv: List[int] = []
        seen = set()
        for _ in range(limit):
            entry = self.tt.data.get(pos.key)
            if not entry or not entry[3]:
                break
            move = entry[3]
            if move in seen:
                break
            seen.add(move)
            if not pos.make(move):
                break
            pv.append(move)
        for move in reversed(pv):
            pos.unmake(move)
        return pv


__all__ = ["Engine", "Limits", "SearchResult", "SearchAbort", "allocate_time",
           "MATE", "MATE_THRESHOLD", "MAX_PLY"]
