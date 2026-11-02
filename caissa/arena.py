"""对局与自测。

两个用途：一是让引擎跟"随机走子"和"只吃子"这类基线对手下一批棋，得到
一个能写进 README 的胜负比；二是给引擎自身做回归——参数改完之后跑一遍，
看强度有没有掉。
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .board import Position, VALUE, move_to
from .san import to_san
from .search import Engine, Limits

Player = Callable[[Position], int]


def random_player(pos: Position) -> int:
    return random.choice(pos.legal_moves())


def material_player(pos: Position) -> int:
    """一层搜索 + 纯子力评估。会吃白送的子，但看不见一步杀。"""
    best, best_score = 0, -10 ** 9
    for move in pos.legal_moves():
        captured = pos.board[move_to(move)] & 7
        gain = VALUE[captured] if captured else 0
        pos.make(move)
        # 走完之后对方的即时反吃
        reply = 0
        for answer in pos.generate_moves(captures=True):
            victim = pos.board[move_to(answer)] & 7
            if victim:
                reply = max(reply, VALUE[victim])
                break
        pos.unmake(move)
        score = gain * 10 - reply + random.random()
        if score > best_score:
            best, best_score = move, score
    return best or random.choice(pos.legal_moves())


def engine_player(engine: Engine, movetime: float = 0.1,
                  depth: int = 0) -> Player:
    def play(pos: Position) -> int:
        limits = Limits(depth=depth) if depth else Limits(movetime=movetime)
        return engine.search(pos.clone(), limits).best_move
    return play


@dataclass
class GameRecord:
    result: str                       # "1-0" / "0-1" / "1/2-1/2"
    moves: List[str] = field(default_factory=list)
    reason: str = ""
    plies: int = 0
    seconds: float = 0.0


def play_game(white: Player, black: Player, max_plies: int = 240,
              start_fen: Optional[str] = None,
              on_move=None) -> GameRecord:
    pos = Position(start_fen) if start_fen else Position()
    san: List[str] = []
    t0 = time.perf_counter()
    reason = ""
    while True:
        if pos.halfmove >= 100:
            reason = "五十回合规则"
            break
        if pos.is_repetition(2):
            reason = "三次重复"
            break
        if pos.insufficient_material():
            reason = "子力不足"
            break
        legal = pos.legal_moves()
        if not legal:
            reason = "将杀" if pos.in_check() else "逼和"
            break
        if len(san) >= max_plies:
            reason = "超过步数上限"
            break
        side = pos.turn
        move = (white if side == 0 else black)(pos)
        if move not in legal:
            reason = "走出非法着法"
            break
        san.append(to_san(pos, move, legal))
        pos.make(move)
        if on_move is not None:
            on_move(pos, san[-1])

    if reason == "将杀":
        result = "0-1" if pos.turn == 0 else "1-0"
    elif reason in ("逼和", "五十回合规则", "三次重复", "子力不足"):
        result = "1/2-1/2"
    else:
        result = "*"
    return GameRecord(result=result, moves=san, reason=reason, plies=len(san),
                      seconds=time.perf_counter() - t0)


def match(a: Player, b: Player, games: int = 10, max_plies: int = 200,
          alternate: bool = True, on_game=None) -> Dict[str, object]:
    """a 与 b 各执黑白若干局。"""
    wins = draws = losses = 0
    records: List[GameRecord] = []
    for i in range(games):
        a_is_white = (i % 2 == 0) if alternate else True
        white, black = (a, b) if a_is_white else (b, a)
        record = play_game(white, black, max_plies=max_plies)
        records.append(record)
        if record.result == "1-0":
            wins += a_is_white
            losses += not a_is_white
        elif record.result == "0-1":
            losses += a_is_white
            wins += not a_is_white
        else:
            draws += 1
        if on_game is not None:
            on_game(i, record, wins, draws, losses)

    total = wins + draws + losses
    score = (wins + draws * 0.5) / total if total else 0.5
    if 0 < score < 1 and total:
        elo = 400 * math.log10(score / (1 - score))
        stderr = math.sqrt(score * (1 - score) / total)
        lo = 400 * math.log10(max(1e-6, (score - 1.96 * stderr))
                              / max(1e-6, 1 - (score - 1.96 * stderr)))
        hi = 400 * math.log10(max(1e-6, (score + 1.96 * stderr))
                              / max(1e-6, 1 - (score + 1.96 * stderr)))
    else:
        elo = float("inf") if score >= 1 else float("-inf")
        lo = hi = elo
    return {"games": total, "wins": wins, "draws": draws, "losses": losses,
            "score": score, "elo": elo, "elo_low": lo, "elo_high": hi,
            "records": records}


__all__ = ["random_player", "material_player", "engine_player", "play_game",
           "match", "GameRecord", "Player"]
