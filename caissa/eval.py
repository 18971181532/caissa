"""局面评估。

评分分成中局（mg）和残局（eg）两套，最后按"还剩多少子力"插值——同一个
王在开局值 -30，在残局值 +30，用一张表是表达不出来的。

各项：

* 材料 + 位置表（PST）
* 象对
* 车在开放线 / 半开放线
* 叠兵、孤兵、通路兵
* 王的兵盾
* 机动性（马象车后的可走格数）

评估函数永远返回"轮到走棋的一方"的分数，和 negamax 的约定一致。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .attacks import (
    BISHOP, BLACK, FILE_A, KING, KNIGHT, KNIGHT_ATTACKS, PAWN, QUEEN, ROOK,
    WHITE, bishop_attacks, queen_attacks, rook_attacks,
)
from .board import Position

MATE = 32000
INF = 32001


def _table(rows: List[List[int]]) -> List[int]:
    """按"第 8 横线在上"的视觉顺序手写，转成按格编号（a1=0）的列表。

    视觉顺序的扁平下标是 ``行 * 8 + 列``，行 = 7 - 秩。所以同一格在两个
    坐标系里差一次"秩取反"，也就是异或 56（0b111000）——不是 63 - sq，
    那个会顺带把左右也翻过去。
    """
    flat = [v for row in rows for v in row]
    if len(flat) != 64:
        raise ValueError("位置表必须是 8×8")
    return [flat[sq ^ 56] for sq in range(64)]


def _mirror(table: List[int]) -> List[int]:
    """黑方的表把棋盘上下翻过来。"""
    return [table[sq ^ 56] for sq in range(64)]


# --------------------------------------------------------------------------
# 位置表
# --------------------------------------------------------------------------

_PAWN_MG = _table([
    [0, 0, 0, 0, 0, 0, 0, 0],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [10, 10, 20, 30, 30, 20, 10, 10],
    [5, 5, 10, 25, 25, 10, 5, 5],
    [0, 0, 0, 20, 20, 0, 0, 0],
    [5, -5, -10, 0, 0, -10, -5, 5],
    [5, 10, 10, -20, -20, 10, 10, 5],
    [0, 0, 0, 0, 0, 0, 0, 0],
])
_PAWN_EG = _table([
    [0, 0, 0, 0, 0, 0, 0, 0],
    [80, 80, 80, 80, 80, 80, 80, 80],
    [50, 50, 50, 50, 50, 50, 50, 50],
    [30, 30, 30, 30, 30, 30, 30, 30],
    [15, 15, 15, 15, 15, 15, 15, 15],
    [5, 5, 5, 5, 5, 5, 5, 5],
    [0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0],
])
_KNIGHT_MG = _table([
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20, 0, 0, 0, 0, -20, -40],
    [-30, 0, 10, 15, 15, 10, 0, -30],
    [-30, 5, 15, 20, 20, 15, 5, -30],
    [-30, 0, 15, 20, 20, 15, 0, -30],
    [-30, 5, 10, 15, 15, 10, 5, -30],
    [-40, -20, 0, 5, 5, 0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
])
_KNIGHT_EG = _table([
    [-50, -40, -30, -30, -30, -30, -40, -50],
    [-40, -20, 0, 0, 0, 0, -20, -40],
    [-30, 0, 10, 15, 15, 10, 0, -30],
    [-30, 5, 15, 25, 25, 15, 5, -30],
    [-30, 0, 15, 25, 25, 15, 0, -30],
    [-30, 5, 10, 15, 15, 10, 5, -30],
    [-40, -20, 0, 5, 5, 0, -20, -40],
    [-50, -40, -30, -30, -30, -30, -40, -50],
])
_BISHOP_MG = _table([
    [-20, -10, -10, -10, -10, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 10, 10, 5, 0, -10],
    [-10, 5, 5, 10, 10, 5, 5, -10],
    [-10, 0, 10, 10, 10, 10, 0, -10],
    [-10, 10, 10, 10, 10, 10, 10, -10],
    [-10, 5, 0, 0, 0, 0, 5, -10],
    [-20, -10, -10, -10, -10, -10, -10, -20],
])
_BISHOP_EG = _BISHOP_MG
_ROOK_MG = _table([
    [0, 0, 0, 0, 0, 0, 0, 0],
    [5, 10, 10, 10, 10, 10, 10, 5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [-5, 0, 0, 0, 0, 0, 0, -5],
    [0, 0, 0, 5, 5, 0, 0, 0],
])
_ROOK_EG = _ROOK_MG
_QUEEN_MG = _table([
    [-20, -10, -10, -5, -5, -10, -10, -20],
    [-10, 0, 0, 0, 0, 0, 0, -10],
    [-10, 0, 5, 5, 5, 5, 0, -10],
    [-5, 0, 5, 5, 5, 5, 0, -5],
    [0, 0, 5, 5, 5, 5, 0, -5],
    [-10, 5, 5, 5, 5, 5, 0, -10],
    [-10, 0, 5, 0, 0, 0, 0, -10],
    [-20, -10, -10, -5, -5, -10, -10, -20],
])
_QUEEN_EG = _QUEEN_MG
_KING_MG = _table([
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-30, -40, -40, -50, -50, -40, -40, -30],
    [-20, -30, -30, -40, -40, -30, -30, -20],
    [-10, -20, -20, -20, -20, -20, -20, -10],
    [20, 20, 0, 0, 0, 0, 20, 20],
    [20, 30, 10, 0, 0, 10, 30, 20],
])
_KING_EG = _table([
    [-50, -40, -30, -20, -20, -30, -40, -50],
    [-30, -20, -10, 0, 0, -10, -20, -30],
    [-30, -10, 20, 30, 30, 20, -10, -30],
    [-30, -10, 30, 40, 40, 30, -10, -30],
    [-30, -10, 30, 40, 40, 30, -10, -30],
    [-30, -10, 20, 30, 30, 20, -10, -30],
    [-30, -30, 0, 0, 0, 0, -30, -30],
    [-50, -30, -30, -30, -30, -30, -30, -50],
])

MAT_MG = {PAWN: 100, KNIGHT: 325, BISHOP: 340, ROOK: 500, QUEEN: 950, KING: 0}
MAT_EG = {PAWN: 120, KNIGHT: 300, BISHOP: 320, ROOK: 540, QUEEN: 950, KING: 0}
PHASE_WEIGHT = {PAWN: 0, KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4, KING: 0}

_PST_MG = {PAWN: _PAWN_MG, KNIGHT: _KNIGHT_MG, BISHOP: _BISHOP_MG,
           ROOK: _ROOK_MG, QUEEN: _QUEEN_MG, KING: _KING_MG}
_PST_EG = {PAWN: _PAWN_EG, KNIGHT: _KNIGHT_EG, BISHOP: _BISHOP_EG,
           ROOK: _ROOK_EG, QUEEN: _QUEEN_EG, KING: _KING_EG}

#: 直接按"棋子编码"索引的表，省掉一次字典查找。0 与 7 是空位。
MG = [None] * 16
EG = [None] * 16
for _pt in (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING):
    MG[_pt] = [MAT_MG[_pt] + v for v in _PST_MG[_pt]]
    MG[8 | _pt] = [MAT_MG[_pt] + v for v in _mirror(_PST_MG[_pt])]
    EG[_pt] = [MAT_EG[_pt] + v for v in _PST_EG[_pt]]
    EG[8 | _pt] = [MAT_EG[_pt] + v for v in _mirror(_PST_EG[_pt])]

_FILES = [FILE_A << f for f in range(8)]

KING_SHIELD = [None, None]
for _color in (WHITE, BLACK):
    _tbl = [0] * 64
    for _sq in range(64):
        _f, _r = _sq & 7, _sq >> 3
        _bb = 0
        for _df in (-1, 0, 1):
            _nf = _f + _df
            if not 0 <= _nf < 8:
                continue
            for _dr in ((1, 2) if _color == WHITE else (-1, -2)):
                _nr = _r + _dr
                if 0 <= _nr < 8:
                    _bb |= 1 << (_nr * 8 + _nf)
        _tbl[_sq] = _bb
    KING_SHIELD[_color] = _tbl

FRONT_SPAN = [None, None]
for _color in (WHITE, BLACK):
    _tbl = [0] * 64
    for _sq in range(64):
        _f, _r = _sq & 7, _sq >> 3
        _bb = 0
        _ranks = range(_r + 1, 8) if _color == WHITE else range(_r - 1, -1, -1)
        for _nr in _ranks:
            for _nf in (_f - 1, _f, _f + 1):
                if 0 <= _nf < 8:
                    _bb |= 1 << (_nr * 8 + _nf)
        _tbl[_sq] = _bb
    FRONT_SPAN[_color] = _tbl

PASSED_MG = (0, 5, 5, 10, 20, 35, 60, 0)
PASSED_EG = (0, 10, 15, 30, 55, 90, 140, 0)

MOBILITY_MG = {KNIGHT: 3, BISHOP: 3, ROOK: 2, QUEEN: 1}
MOBILITY_EG = {KNIGHT: 2, BISHOP: 3, ROOK: 3, QUEEN: 2}


def evaluate(pos: Position, detail: Optional[Dict[str, int]] = None) -> int:
    """返回"轮到走棋的一方"看到的分数（厘兵）。正数表示走棋方占优。"""
    board = pos.board
    mg = [0, 0]
    eg = [0, 0]
    phase = 0

    for sq in range(64):
        piece = board[sq]
        if not piece:
            continue
        color = piece >> 3
        mg[color] += MG[piece][sq]
        eg[color] += EG[piece][sq]
        phase += PHASE_WEIGHT[piece & 7]

    if phase > 24:
        phase = 24

    if detail is not None:
        detail["material"] = (mg[WHITE] - mg[BLACK]) if pos.turn == WHITE else (mg[BLACK] - mg[WHITE])

    # ---- 兵形 ----
    pawn_mg = [0, 0]
    pawn_eg = [0, 0]
    for color in (WHITE, BLACK):
        them = color ^ 1
        pawns = pos.bb[(color << 3) | PAWN]
        if not pawns:
            continue
        enemy_pawns = pos.bb[(them << 3) | PAWN]
        counts = [0] * 8
        b = pawns
        while b:
            bit = b & -b
            sq = bit.bit_length() - 1
            b ^= bit
            f = sq & 7
            counts[f] += 1
            # 孤兵：左右两条邻线上都没有己方兵
            neighbour = 0
            if f > 0:
                neighbour |= _FILES[f - 1]
            if f < 7:
                neighbour |= _FILES[f + 1]
            if not (pawns & neighbour):
                pawn_mg[color] -= 14
                pawn_eg[color] -= 10
            # 通路兵：前方三条线上都没有对方兵
            if not (FRONT_SPAN[color][sq] & enemy_pawns):
                rel = (sq >> 3) if color == WHITE else 7 - (sq >> 3)
                pawn_mg[color] += PASSED_MG[rel]
                pawn_eg[color] += PASSED_EG[rel]
        doubled = sum(max(0, c - 1) for c in counts)
        pawn_mg[color] -= doubled * 12
        pawn_eg[color] -= doubled * 18

    # ---- 象对 / 车在开放线 ----
    extra_mg = [0, 0]
    extra_eg = [0, 0]
    for color in (WHITE, BLACK):
        if pos.bb[(color << 3) | BISHOP].bit_count() >= 2:
            extra_mg[color] += 28
            extra_eg[color] += 48
        rooks = pos.bb[(color << 3) | ROOK]
        while rooks:
            bit = rooks & -rooks
            sq = bit.bit_length() - 1
            rooks ^= bit
            f = sq & 7
            own_pawns = pos.bb[(color << 3) | PAWN] & _FILES[f]
            enemy_pawns = pos.bb[((color ^ 1) << 3) | PAWN] & _FILES[f]
            if not own_pawns:
                if not enemy_pawns:
                    extra_mg[color] += 26
                    extra_eg[color] += 12
                else:
                    extra_mg[color] += 12
                    extra_eg[color] += 6

    # ---- 王的兵盾 ----
    shield = [0, 0]
    for color in (WHITE, BLACK):
        ksq = pos.king_square(color)
        if ksq < 0:
            continue
        rank = ksq >> 3
        home = rank <= 1 if color == WHITE else rank >= 6
        if not home:
            continue
        pawns = pos.bb[(color << 3) | PAWN]
        missing = 3 - (KING_SHIELD[color][ksq] & pawns).bit_count()
        shield[color] = -missing * 11

    # ---- 机动性 ----
    # 只算马、象、车。后的攻击要扫八条射线，代价是别的一倍，而它能走多宽
    # 基本已经被位置表和兵形解释掉了。
    mob = [0, 0]
    occ = pos.all
    for color in (WHITE, BLACK):
        own = pos.occ[color]
        bb = pos.bb
        base = color << 3
        total = 0
        pieces = bb[base | KNIGHT]
        while pieces:
            bit = pieces & -pieces
            sq = bit.bit_length() - 1
            pieces ^= bit
            total += (KNIGHT_ATTACKS[sq] & ~own).bit_count()
        for pt, fn in ((BISHOP, bishop_attacks), (ROOK, rook_attacks)):
            pieces = bb[base | pt]
            while pieces:
                bit = pieces & -pieces
                sq = bit.bit_length() - 1
                pieces ^= bit
                total += (fn(sq, occ) & ~own).bit_count()
        mob[color] = total

    mg[WHITE] += pawn_mg[WHITE] + extra_mg[WHITE] + mob[WHITE] * 1
    mg[BLACK] += pawn_mg[BLACK] + extra_mg[BLACK] + mob[BLACK] * 1
    eg[WHITE] += pawn_eg[WHITE] + extra_eg[WHITE] + mob[WHITE] * 2
    eg[BLACK] += pawn_eg[BLACK] + extra_eg[BLACK] + mob[BLACK] * 2
    mg[WHITE] += shield[WHITE]
    mg[BLACK] += shield[BLACK]

    if detail is not None:
        detail["pawns"] = pawn_mg[WHITE] - pawn_mg[BLACK]
        detail["pieces"] = extra_mg[WHITE] - extra_mg[BLACK]
        detail["shield"] = shield[WHITE] - shield[BLACK]
        detail["mobility"] = mob[WHITE] - mob[BLACK]

    score = ((mg[WHITE] - mg[BLACK]) * (24 - phase)
             + (eg[WHITE] - eg[BLACK]) * phase) // 24

    if detail is not None:
        detail["mg"] = mg[WHITE] - mg[BLACK]
        detail["eg"] = eg[WHITE] - eg[BLACK]
        detail["phase"] = phase

    if pos.turn == WHITE:
        score += 10
    else:
        score -= 10
    return score if pos.turn == WHITE else -score


def format_score(cp: int) -> str:
    """把一个分数写成 '+0.35' 或 '#-3'。"""
    if abs(cp) > MATE - 200:
        return "#" if cp > 0 else "#-"
    return f"{cp / 100:+.2f}"


__all__ = ["evaluate", "format_score", "MATE", "INF", "MG", "EG"]
