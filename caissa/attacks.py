"""预计算的攻击表。

三张基础表（马、王、兵）直接枚举落点；滑子（象、车、后）用八个方向的射线表，
配合"最近的阻挡子"把射线截断。

没有用 magic bitboard：那套东西的价值在于把滑子攻击压成一次查表，代价是
要搜魔术数、要建一张几十 KB 的表，还得处理边界。Python 里查表本身就有
字典/列表下标开销，省下的那点时间不足以抵消多出来的复杂度。
"""

from __future__ import annotations

MASK64 = (1 << 64) - 1

FILE_A = 0x0101010101010101
FILE_H = 0x8080808080808080
RANK_1 = 0x00000000000000FF
RANK_2 = 0x000000000000FF00
RANK_3 = 0x0000000000FF0000
RANK_4 = 0x00000000FF000000
RANK_5 = 0x000000FF00000000
RANK_6 = 0x0000FF0000000000
RANK_7 = 0x00FF000000000000
RANK_8 = 0xFF00000000000000

WHITE, BLACK = 0, 1

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6

NORTH, NORTH_EAST, EAST, SOUTH_EAST, SOUTH, SOUTH_WEST, WEST, NORTH_WEST = range(8)

# 方向用 (df, dr)：f 是列，r 是行，行号 0 是第 1 横线。
_DIRS = ((0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1))

# 沿该方向走，格编号（rank*8+file）是变大还是变小。滑子截断时要用：
# 变大取最低位的阻挡子，变小取最高位的。
_POSITIVE = (True, True, True, False, False, False, False, True)


def square(file: int, rank: int) -> int:
    return rank * 8 + file


def file_of(sq: int) -> int:
    return sq & 7


def rank_of(sq: int) -> int:
    return sq >> 3


def name_of(sq: int) -> str:
    """44 → 'e6'。"""
    return "abcdefgh"[sq & 7] + str((sq >> 3) + 1)


def parse_square(name: str) -> int:
    """'e6' → 44。"""
    if len(name) != 2:
        raise ValueError(f"不是合法的格子：{name!r}")
    f = "abcdefgh".find(name[0].lower())
    r = "12345678".find(name[1])
    if f < 0 or r < 0:
        raise ValueError(f"不是合法的格子：{name!r}")
    return r * 8 + f


def _leaper(deltas):
    table = [0] * 64
    for sq in range(64):
        f, r = sq & 7, sq >> 3
        bb = 0
        for df, dr in deltas:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                bb |= 1 << (nr * 8 + nf)
        table[sq] = bb
    return table


KNIGHT_ATTACKS = _leaper(((1, 2), (2, 1), (2, -1), (1, -2),
                          (-1, -2), (-2, -1), (-2, 1), (-1, 2)))
KING_ATTACKS = _leaper(((0, 1), (1, 1), (1, 0), (1, -1),
                        (0, -1), (-1, -1), (-1, 0), (-1, 1)))
PAWN_ATTACKS = (
    _leaper(((-1, 1), (1, 1))),        # 白兵向上吃
    _leaper(((-1, -1), (1, -1))),      # 黑兵向下吃
)


def _rays(df: int, dr: int):
    table = [0] * 64
    for sq in range(64):
        f, r = sq & 7, sq >> 3
        bb = 0
        nf, nr = f + df, r + dr
        while 0 <= nf < 8 and 0 <= nr < 8:
            bb |= 1 << (nr * 8 + nf)
            nf += df
            nr += dr
        table[sq] = bb
    return table


RAYS = tuple(_rays(df, dr) for df, dr in _DIRS)
RAYS_N, RAYS_NE, RAYS_E, RAYS_SE, RAYS_S, RAYS_SW, RAYS_W, RAYS_NW = RAYS


def _scan(table, sq: int, occ: int, positive: bool) -> int:
    """沿一条射线走，撞到第一个子就停（含该子所在格）。"""
    ray = table[sq]
    blockers = ray & occ
    if not blockers:
        return ray
    if positive:
        first = (blockers & -blockers).bit_length() - 1
    else:
        first = blockers.bit_length() - 1
    # ray 与 table[first] 是同一条射线的前后两段，异或掉就是"到 first 为止"
    return ray ^ table[first]


def bishop_attacks(sq: int, occ: int) -> int:
    return (_scan(RAYS_NE, sq, occ, True) | _scan(RAYS_NW, sq, occ, True)
            | _scan(RAYS_SE, sq, occ, False) | _scan(RAYS_SW, sq, occ, False))


def rook_attacks(sq: int, occ: int) -> int:
    return (_scan(RAYS_N, sq, occ, True) | _scan(RAYS_E, sq, occ, True)
            | _scan(RAYS_S, sq, occ, False) | _scan(RAYS_W, sq, occ, False))


def queen_attacks(sq: int, occ: int) -> int:
    return bishop_attacks(sq, occ) | rook_attacks(sq, occ)


SLIDER_ATTACKS = {BISHOP: bishop_attacks, ROOK: rook_attacks, QUEEN: queen_attacks}

__all__ = [
    "MASK64", "FILE_A", "FILE_H", "RANK_1", "RANK_2", "RANK_3", "RANK_4",
    "RANK_5", "RANK_6", "RANK_7", "RANK_8", "WHITE", "BLACK", "PAWN", "KNIGHT",
    "BISHOP", "ROOK", "QUEEN", "KING", "KNIGHT_ATTACKS", "KING_ATTACKS",
    "PAWN_ATTACKS", "RAYS", "bishop_attacks", "rook_attacks", "queen_attacks",
    "SLIDER_ATTACKS", "square", "file_of", "rank_of", "name_of", "parse_square",
]
