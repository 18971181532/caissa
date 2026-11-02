"""棋盘状态、走子生成与撤销。

格子编号用 LERF：a1 = 0，h1 = 7，a8 = 56，h8 = 63。这样"向北"就是 +8，
"向东"就是 +1，位板的移位方向和棋盘的视觉方向一致，少一层心智负担。

棋子编码 ``color << 3 | type``：白兵 = 1，黑兵 = 9。右移三位得颜色，
与 7 得兵种，判断颜色时不需要额外分支。

着法压成一个整数，避免在搜索里创建几百万个对象::

    bits  0-5   起点（0-63）
    bits  6-11  终点（0-63）
    bits 12-14  升变棋子（0 = 不升变，否则 2-5）
    bits 15-18  标志位：吃子 / 吃过路兵 / 易位 / 兵走两格
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

from .attacks import (
    BISHOP, BLACK, FILE_A, FILE_H, KING, KNIGHT, KNIGHT_ATTACKS, KING_ATTACKS,
    MASK64, PAWN, PAWN_ATTACKS, QUEEN, RANK_1, RANK_3, RANK_6, RANK_8, ROOK,
    WHITE, bishop_attacks, name_of, parse_square, queen_attacks, rank_of,
    rook_attacks,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

FLAG_CAPTURE = 1
FLAG_EP = 2
FLAG_CASTLE = 4
FLAG_DOUBLE = 8

PIECE_CHARS = ".PNBRQK..pnbrqk.."

PIECE_NAMES = {
    PAWN: "pawn", KNIGHT: "knight", BISHOP: "bishop",
    ROOK: "rook", QUEEN: "queen", KING: "king",
}

#: 子力价值，单位是"厘兵"（1 兵 = 100）。
VALUE = {0: 0, PAWN: 100, KNIGHT: 320, BISHOP: 330, ROOK: 500, QUEEN: 900, KING: 20000}

# 某个格子被动过之后，还能保留哪些易位权。
CASTLE_MASK = [15] * 64
CASTLE_MASK[4] = 15 & ~3      # e1：白方两侧全丢
CASTLE_MASK[7] = 15 & ~1      # h1：丢短易位
CASTLE_MASK[0] = 15 & ~2      # a1：丢长易位
CASTLE_MASK[60] = 15 & ~12    # e8
CASTLE_MASK[63] = 15 & ~4     # h8
CASTLE_MASK[56] = 15 & ~8     # a8

CASTLE_WK, CASTLE_WQ, CASTLE_BK, CASTLE_BQ = 1, 2, 4, 8


# --------------------------------------------------------------------------
# 着法打包
# --------------------------------------------------------------------------

def encode(frm: int, to: int, promo: int = 0, flags: int = 0) -> int:
    return frm | (to << 6) | (promo << 12) | (flags << 15)


def move_from(move: int) -> int:
    return move & 63


def move_to(move: int) -> int:
    return (move >> 6) & 63


def move_promo(move: int) -> int:
    return (move >> 12) & 7


def move_flags(move: int) -> int:
    return move >> 15


def move_uci(move: int, chess960: bool = False) -> str:
    """'e2e4'、'e7e8q'。"""
    s = name_of(move & 63) + name_of((move >> 6) & 63)
    promo = (move >> 12) & 7
    if promo:
        s += "nbrq"[promo - KNIGHT]
    return s


def parse_uci(text: str) -> Optional[int]:
    text = text.strip().lower()
    if len(text) < 4:
        return None
    try:
        frm = parse_square(text[0:2])
        to = parse_square(text[2:4])
    except ValueError:
        return None
    promo = 0
    if len(text) >= 5 and text[4] in "nbrq":
        promo = "nbrq".index(text[4]) + KNIGHT
    return encode(frm, to, promo)


# --------------------------------------------------------------------------
# Zobrist
# --------------------------------------------------------------------------

_rng = random.Random(0x5EED_CA15)

Z_PIECE = [[_rng.getrandbits(64) for _ in range(64)] for _ in range(16)]
Z_CASTLE = [_rng.getrandbits(64) for _ in range(16)]
Z_EP = [_rng.getrandbits(64) for _ in range(65)]      # 下标 64 表示"无过路兵"
Z_TURN = _rng.getrandbits(64)


def _bits(bb: int):
    while bb:
        bit = bb & -bb
        yield bit.bit_length() - 1
        bb ^= bit


class Position:
    """一个局面。make/unmake 成对使用，不复制对象。"""

    __slots__ = ("bb", "occ", "all", "board", "turn", "castling", "ep",
                 "halfmove", "fullmove", "key", "undo", "keys")

    def __init__(self, fen: str = START_FEN):
        self.bb = [0] * 16
        self.occ = [0, 0]
        self.all = 0
        self.board = [0] * 64
        self.turn = WHITE
        self.castling = 0
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.key = 0
        self.undo: List[Tuple[int, int, int, int, int]] = []
        self.keys: List[int] = []
        self.set_fen(fen)

    # -- 基本操作 ---------------------------------------------------------

    def _add(self, sq: int, piece: int) -> None:
        b = 1 << sq
        self.bb[piece] |= b
        self.occ[piece >> 3] |= b
        self.all |= b
        self.board[sq] = piece

    def _remove(self, sq: int, piece: int) -> None:
        b = 1 << sq
        self.bb[piece] ^= b
        self.occ[piece >> 3] ^= b
        self.all ^= b
        self.board[sq] = 0

    def clear(self) -> None:
        self.bb = [0] * 16
        self.occ = [0, 0]
        self.all = 0
        self.board = [0] * 64
        self.undo.clear()
        self.keys.clear()

    def piece_at(self, sq: int) -> int:
        return self.board[sq]

    def king_square(self, color: int) -> int:
        bb = self.bb[(color << 3) | KING]
        if not bb:
            return -1
        return (bb & -bb).bit_length() - 1

    # -- FEN --------------------------------------------------------------

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError(f"FEN 字段不足：{fen!r}")
        self.clear()
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError(f"FEN 必须正好 8 行：{fen!r}")
        for i, row in enumerate(rows):
            rank = 7 - i
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                    continue
                if ch not in PIECE_CHARS:
                    raise ValueError(f"FEN 里有不认识的字符 {ch!r}")
                color = WHITE if ch.isupper() else BLACK
                piece = (color << 3) | PIECE_CHARS.index(ch) % 8
                if file > 7:
                    raise ValueError(f"FEN 第 {8 - i} 行超出 8 列：{row!r}")
                self._add(rank * 8 + file, piece)
                file += 1
            if file != 8:
                raise ValueError(f"FEN 第 {8 - i} 行不是 8 列：{row!r}")

        self.turn = WHITE if parts[1] == "w" else BLACK

        self.castling = 0
        if parts[2] != "-":
            for ch in parts[2]:
                self.castling |= {"K": 1, "Q": 2, "k": 4, "q": 8}.get(ch, 0)
        # 权利与实际棋子对不上时（手改过的 FEN），以棋盘为准
        if not (self.bb[(WHITE << 3) | KING] & (1 << 4)):
            self.castling &= ~(CASTLE_WK | CASTLE_WQ)
        if not (self.bb[(BLACK << 3) | KING] & (1 << 60)):
            self.castling &= ~(CASTLE_BK | CASTLE_BQ)
        if not (self.bb[(WHITE << 3) | ROOK] & (1 << 7)):
            self.castling &= ~CASTLE_WK
        if not (self.bb[(WHITE << 3) | ROOK] & (1 << 0)):
            self.castling &= ~CASTLE_WQ
        if not (self.bb[(BLACK << 3) | ROOK] & (1 << 63)):
            self.castling &= ~CASTLE_BK
        if not (self.bb[(BLACK << 3) | ROOK] & (1 << 56)):
            self.castling &= ~CASTLE_BQ

        self.ep = -1
        if parts[3] != "-":
            try:
                self.ep = parse_square(parts[3])
            except ValueError:
                self.ep = -1
            if self.ep >= 0:
                # 过路兵格后面必须有对方刚推上来的兵，否则这一格是假的
                back = self.ep - 8 if self.turn == WHITE else self.ep + 8
                if not (self.board[self.ep] == 0 and 0 <= back < 64
                        and self.board[back] == ((self.turn ^ 1) << 3 | PAWN)):
                    self.ep = -1

        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].lstrip("+-").isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        self.key = self._compute_key()
        self.keys.append(self.key)

    def _compute_key(self) -> int:
        key = 0
        for sq in range(64):
            piece = self.board[sq]
            if piece:
                key ^= Z_PIECE[piece][sq]
        key ^= Z_CASTLE[self.castling]
        key ^= Z_EP[self.ep if self.ep >= 0 else 64]
        if self.turn == BLACK:
            key ^= Z_TURN
        return key

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for file in range(8):
                piece = self.board[rank * 8 + file]
                if piece:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += PIECE_CHARS[piece]
                else:
                    empty += 1
            if empty:
                row += str(empty)
            rows.append(row)
        castle = ""
        if self.castling & CASTLE_WK:
            castle += "K"
        if self.castling & CASTLE_WQ:
            castle += "Q"
        if self.castling & CASTLE_BK:
            castle += "k"
        if self.castling & CASTLE_BQ:
            castle += "q"
        return "%s %s %s %s %d %d" % (
            "/".join(rows), "w" if self.turn == WHITE else "b",
            castle or "-", name_of(self.ep) if self.ep >= 0 else "-",
            self.halfmove, self.fullmove)

    def clone(self) -> "Position":
        other = Position.__new__(Position)
        other.bb = list(self.bb)
        other.occ = list(self.occ)
        other.all = self.all
        other.board = list(self.board)
        other.turn = self.turn
        other.castling = self.castling
        other.ep = self.ep
        other.halfmove = self.halfmove
        other.fullmove = self.fullmove
        other.key = self.key
        other.undo = []
        other.keys = list(self.keys)
        return other

    # -- 攻击 -------------------------------------------------------------

    def is_attacked(self, sq: int, by_color: int) -> bool:
        """by_color 是否有子能吃 sq。"""
        bb = self.bb
        base = by_color << 3
        if PAWN_ATTACKS[by_color ^ 1][sq] & bb[base | PAWN]:
            return True
        if KNIGHT_ATTACKS[sq] & bb[base | KNIGHT]:
            return True
        if KING_ATTACKS[sq] & bb[base | KING]:
            return True
        occ = self.all
        diag = bb[base | BISHOP] | bb[base | QUEEN]
        if diag and (bishop_attacks(sq, occ) & diag):
            return True
        line = bb[base | ROOK] | bb[base | QUEEN]
        if line and (rook_attacks(sq, occ) & line):
            return True
        return False

    def attackers_to(self, sq: int, occ: int) -> int:
        """所有能吃 sq 的子（黑白都算），用作静态交换评估的输入。"""
        bb = self.bb
        out = PAWN_ATTACKS[BLACK][sq] & bb[(WHITE << 3) | PAWN]
        out |= PAWN_ATTACKS[WHITE][sq] & bb[(BLACK << 3) | PAWN]
        out |= KNIGHT_ATTACKS[sq] & (bb[KNIGHT] | bb[(BLACK << 3) | KNIGHT])
        out |= KING_ATTACKS[sq] & (bb[KING] | bb[(BLACK << 3) | KING])
        out |= bishop_attacks(sq, occ) & (bb[BISHOP] | bb[QUEEN]
                                          | bb[(BLACK << 3) | BISHOP]
                                          | bb[(BLACK << 3) | QUEEN])
        out |= rook_attacks(sq, occ) & (bb[ROOK] | bb[(BLACK << 3) | ROOK]
                                        | bb[QUEEN] | bb[(BLACK << 3) | QUEEN])
        return out

    def in_check(self) -> bool:
        sq = self.king_square(self.turn)
        return sq >= 0 and self.is_attacked(sq, self.turn ^ 1)

    def checkers(self) -> int:
        sq = self.king_square(self.turn)
        if sq < 0:
            return 0
        return self.attackers_to(sq, self.all) & self.occ[self.turn ^ 1]

    # -- 着法生成 ---------------------------------------------------------

    def generate_moves(self, captures: bool = False) -> List[int]:
        """生成伪合法着法。是否送将交给 make() 判。"""
        moves: List[int] = []
        append = moves.append
        us = self.turn
        them = us ^ 1
        occ = self.all
        own = self.occ[us]
        enemy = self.occ[them]
        bb = self.bb
        base = us << 3
        not_occ = ~occ & MASK64

        # ---- 兵 ----
        pawns = bb[base | PAWN]
        if pawns:
            if us == WHITE:
                single = (pawns << 8) & not_occ
                double = ((single & RANK_3) << 8) & not_occ
                caps_w = ((pawns << 7) & ~FILE_H) & enemy
                caps_e = ((pawns << 9) & ~FILE_A) & enemy
                promo_rank, push = RANK_8, 8
            else:
                single = (pawns >> 8) & not_occ
                double = ((single & RANK_6) >> 8) & not_occ
                caps_w = ((pawns >> 9) & ~FILE_H) & enemy
                caps_e = ((pawns >> 7) & ~FILE_A) & enemy
                promo_rank, push = RANK_1, -8

            if not captures:
                b = single & ~promo_rank
                while b:
                    bit = b & -b
                    to = bit.bit_length() - 1
                    b ^= bit
                    append((to - push) | (to << 6))
                b = double
                while b:
                    bit = b & -b
                    to = bit.bit_length() - 1
                    b ^= bit
                    append((to - 2 * push) | (to << 6) | (FLAG_DOUBLE << 15))

            b = single & promo_rank
            while b:
                bit = b & -b
                to = bit.bit_length() - 1
                b ^= bit
                frm = to - push
                for pt in (QUEEN, ROOK, BISHOP, KNIGHT):
                    append(frm | (to << 6) | (pt << 12))

            for dest, delta in ((caps_w, push - 1), (caps_e, push + 1)):
                b = dest
                while b:
                    bit = b & -b
                    to = bit.bit_length() - 1
                    b ^= bit
                    frm = to - delta
                    if (1 << to) & promo_rank:
                        for pt in (QUEEN, ROOK, BISHOP, KNIGHT):
                            append(frm | (to << 6) | (pt << 12) | (FLAG_CAPTURE << 15))
                    else:
                        append(frm | (to << 6) | (FLAG_CAPTURE << 15))

            if self.ep >= 0:
                b = PAWN_ATTACKS[them][self.ep] & pawns
                while b:
                    bit = b & -b
                    frm = bit.bit_length() - 1
                    b ^= bit
                    append(frm | (self.ep << 6)
                           | (FLAG_CAPTURE << 15) | (FLAG_EP << 15))

        # ---- 马 ----
        pieces = bb[base | KNIGHT]
        while pieces:
            bit = pieces & -pieces
            frm = bit.bit_length() - 1
            pieces ^= bit
            targets = KNIGHT_ATTACKS[frm] & ~own
            if captures:
                targets &= enemy
            while targets:
                t = targets & -targets
                to = t.bit_length() - 1
                targets ^= t
                append(frm | (to << 6)
                       | (((FLAG_CAPTURE << 15) if (enemy >> to) & 1 else 0)))

        # ---- 象 / 车 / 后 ----
        for pt, attack in ((BISHOP, bishop_attacks), (ROOK, rook_attacks),
                           (QUEEN, queen_attacks)):
            pieces = bb[base | pt]
            while pieces:
                bit = pieces & -pieces
                frm = bit.bit_length() - 1
                pieces ^= bit
                targets = attack(frm, occ) & ~own
                if captures:
                    targets &= enemy
                while targets:
                    t = targets & -targets
                    to = t.bit_length() - 1
                    targets ^= t
                    append(frm | (to << 6)
                           | (((FLAG_CAPTURE << 15) if (enemy >> to) & 1 else 0)))

        # ---- 王 ----
        king = bb[base | KING]
        if king:
            frm = (king & -king).bit_length() - 1
            targets = KING_ATTACKS[frm] & ~own
            if captures:
                targets &= enemy
            while targets:
                t = targets & -targets
                to = t.bit_length() - 1
                targets ^= t
                append(frm | (to << 6)
                       | (((FLAG_CAPTURE << 15) if (enemy >> to) & 1 else 0)))

        # ---- 易位 ----
        if not captures and self.castling:
            c = self.castling
            if us == WHITE:
                if (c & CASTLE_WK and not (occ & 0x60)
                        and not self.is_attacked(4, them)
                        and not self.is_attacked(5, them)):
                    append(4 | (6 << 6) | (FLAG_CASTLE << 15))
                if (c & CASTLE_WQ and not (occ & 0x0E)
                        and not self.is_attacked(4, them)
                        and not self.is_attacked(3, them)):
                    append(4 | (2 << 6) | (FLAG_CASTLE << 15))
            else:
                if (c & CASTLE_BK and not (occ & 0x6000000000000000)
                        and not self.is_attacked(60, them)
                        and not self.is_attacked(61, them)):
                    append(60 | (62 << 6) | (FLAG_CASTLE << 15))
                if (c & CASTLE_BQ and not (occ & 0x0E00000000000000)
                        and not self.is_attacked(60, them)
                        and not self.is_attacked(59, them)):
                    append(60 | (58 << 6) | (FLAG_CASTLE << 15))

        return moves

    def legal_moves(self) -> List[int]:
        out = []
        for move in self.generate_moves():
            if self.make(move):
                out.append(move)
                self.unmake(move)
        return out

    def has_legal_move(self) -> bool:
        for move in self.generate_moves():
            if self.make(move):
                self.unmake(move)
                return True
        return False

    def resolve(self, move: int) -> Optional[int]:
        """把外部着法（UCI 那种只带起终点的）对到内部编码上。

        ``parse_uci("e2e4")`` 看不出这一步是双步、易位还是吃过路兵，而这些
        标记决定了 make 的副作用（过路兵格、车的移动）。所以外部着法必须先
        经过这一层，才能在棋盘上正确执行。
        """
        ident = move & 0x7FFF          # frm | to << 6 | promo << 12
        for candidate in self.generate_moves():
            if (candidate & 0x7FFF) != ident:
                continue
            if self.make(candidate):
                self.unmake(candidate)
                return candidate
            return None
        return None

    # -- 走子 / 撤销 -------------------------------------------------------

    def make(self, move: int) -> bool:
        """执行着法并返回是否合法。不合法的会自己撤销干净。"""
        frm = move & 63
        to = (move >> 6) & 63
        promo = (move >> 12) & 7
        flags = move >> 15
        us = self.turn
        them = us ^ 1
        piece = self.board[frm]
        key = self.key

        cap_sq = -1
        captured = 0
        if flags & FLAG_EP:
            cap_sq = to - 8 if us == WHITE else to + 8
            captured = self.board[cap_sq]
        elif self.board[to]:
            cap_sq = to
            captured = self.board[to]

        self.undo.append((captured, self.castling, self.ep, self.halfmove, key))

        # 拿起
        self._remove(frm, piece)
        key ^= Z_PIECE[piece][frm]

        # 吃掉
        if cap_sq >= 0:
            self._remove(cap_sq, captured)
            key ^= Z_PIECE[captured][cap_sq]
            self.halfmove = 0

        # 放下（可能升变）
        if promo:
            piece = (us << 3) | promo
        self._add(to, piece)
        key ^= Z_PIECE[piece][to]
        if promo or (piece & 7) == PAWN:
            self.halfmove = 0

        # 易位的车
        if flags & FLAG_CASTLE:
            if to == 6:
                rf, rt = 7, 5
            elif to == 2:
                rf, rt = 0, 3
            elif to == 62:
                rf, rt = 63, 61
            else:
                rf, rt = 56, 59
            rook = self.board[rf]
            self._remove(rf, rook)
            key ^= Z_PIECE[rook][rf]
            self._add(rt, rook)
            key ^= Z_PIECE[rook][rt]

        # 易位权
        new_castle = self.castling & CASTLE_MASK[frm] & CASTLE_MASK[to]
        if new_castle != self.castling:
            key ^= Z_CASTLE[self.castling] ^ Z_CASTLE[new_castle]
            self.castling = new_castle

        # 过路兵格
        ep = (frm + 8) if (flags & FLAG_DOUBLE and us == WHITE) else (
            (frm - 8) if (flags & FLAG_DOUBLE) else -1)
        if ep != self.ep:
            key ^= Z_EP[self.ep if self.ep >= 0 else 64]
            key ^= Z_EP[ep if ep >= 0 else 64]
            self.ep = ep

        self.turn = them
        key ^= Z_TURN
        if us == BLACK:
            self.fullmove += 1
        self.halfmove += 0 if (promo or captured or (piece & 7) == PAWN) else 1
        # 上面已经把 halfmove 归零过了，这里只处理没吃没动兵的情况
        self.key = key
        self.keys.append(key)

        if self.is_attacked(self.king_square(us), them):
            self.unmake(move)
            return False
        return True

    def unmake(self, move: int) -> None:
        captured, castling, ep, halfmove, key = self.undo.pop()
        self.keys.pop()
        self.turn ^= 1
        us = self.turn
        if us == BLACK:
            self.fullmove -= 1

        frm = move & 63
        to = (move >> 6) & 63
        promo = (move >> 12) & 7
        flags = move >> 15

        # 先按"升变后的子"从终点摘掉，再把兵放回起点。
        # 两件事不能合成一次：位的编码不同。
        piece = self.board[to]
        self._remove(to, piece)
        self._add(frm, ((us << 3) | PAWN) if promo else piece)

        if captured:
            cap_sq = to
            if flags & FLAG_EP:
                cap_sq = to - 8 if us == WHITE else to + 8
            self._add(cap_sq, captured)

        if flags & FLAG_CASTLE:
            if to == 6:
                rf, rt = 7, 5
            elif to == 2:
                rf, rt = 0, 3
            elif to == 62:
                rf, rt = 63, 61
            else:
                rf, rt = 56, 59
            rook = self.board[rt]
            self._remove(rt, rook)
            self._add(rf, rook)

        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.key = key

    def null_move(self) -> None:
        """空着：只翻转走子方与过路兵格（空着剪枝要用）。"""
        self.undo.append((0, self.castling, self.ep, self.halfmove, self.key))
        key = self.key
        if self.ep >= 0:
            key ^= Z_EP[self.ep]
            self.ep = -1
            key ^= Z_EP[64]
        key ^= Z_TURN
        self.turn ^= 1
        self.key = key
        self.keys.append(key)

    def unmake_null(self) -> None:
        captured, castling, ep, halfmove, key = self.undo.pop()
        self.keys.pop()
        self.turn ^= 1
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.key = key

    # -- 局面判断 ---------------------------------------------------------

    def is_repetition(self, times: int = 1) -> bool:
        """当前局面在历史上是否已经出现过 times 次（同一方走棋才算）。"""
        keys = self.keys
        n = len(keys)
        if n < 3:
            return False
        key = keys[-1]
        count = 0
        limit = max(0, n - 1 - max(self.halfmove, 0))
        for i in range(n - 3, limit - 1, -2):
            if keys[i] == key:
                count += 1
                if count >= times:
                    return True
        return False

    def is_draw(self) -> bool:
        if self.halfmove >= 100:
            return True
        if self.is_repetition(2):
            return True
        return self.insufficient_material()

    def insufficient_material(self) -> bool:
        if self.bb[PAWN] or self.bb[BLACK << 3 | PAWN]:
            return False
        for pt in (ROOK, QUEEN):
            if self.bb[pt] or self.bb[(BLACK << 3) | pt]:
                return False
        minors_w = self.bb[KNIGHT].bit_count() + self.bb[BISHOP].bit_count()
        minors_b = (self.bb[(BLACK << 3) | KNIGHT].bit_count()
                    + self.bb[(BLACK << 3) | BISHOP].bit_count())
        return minors_w <= 1 and minors_b <= 1

    def phase(self) -> int:
        """24 = 开局，0 = 残局。评估时用来在两张表之间插值。"""
        p = (self.bb[KNIGHT].bit_count() + self.bb[(BLACK << 3) | KNIGHT].bit_count()) * 1
        p += (self.bb[BISHOP].bit_count() + self.bb[(BLACK << 3) | BISHOP].bit_count()) * 1
        p += (self.bb[ROOK].bit_count() + self.bb[(BLACK << 3) | ROOK].bit_count()) * 2
        p += (self.bb[QUEEN].bit_count() + self.bb[(BLACK << 3) | QUEEN].bit_count()) * 4
        return min(p, 24)

    # -- 静态交换评估 -----------------------------------------------------

    def see(self, move: int) -> int:
        """静态交换评估：假设双方都用最便宜的子继续吃，这步棋净赚多少。

        做法是经典的 gain 数组——先把整条吃子序列的"每步赚多少"列出来，
        再从末尾往回做一次极大极小。序列长度很少有超过 4 的。
        """
        frm = move & 63
        to = (move >> 6) & 63
        flags = move >> 15
        promo = (move >> 12) & 7
        us = self.turn
        them = us ^ 1

        if flags & FLAG_EP:
            gain = [VALUE[PAWN]]
            occ = ((self.all ^ (1 << frm) ^ (1 << (to - 8 if us == WHITE else to + 8)))
                   | (1 << to))
        elif self.board[to]:
            gain = [VALUE[self.board[to] & 7]]
            occ = (self.all ^ (1 << frm)) | (1 << to)
        else:
            # 不吃子的安静着法：只有升变有确定收益
            return (VALUE[promo] - VALUE[PAWN]) if promo else 0

        # 刚落到 to 上的那枚子的价值
        moved = (us << 3) | (promo if promo else (self.board[frm] & 7))
        on_target = VALUE[moved & 7]
        side = them

        while True:
            pool = self.attackers_to(to, occ) & self.occ[side] & occ
            if not pool:
                break
            best_sq = -1
            best_val = 1 << 30
            b = pool
            while b:
                bit = b & -b
                sq = bit.bit_length() - 1
                b ^= bit
                val = VALUE[self.board[sq] & 7]
                if val < best_val:
                    best_val = val
                    best_sq = sq
            gain.append(on_target - gain[-1])
            on_target = best_val
            occ &= ~(1 << best_sq)
            side ^= 1

        for i in range(len(gain) - 2, -1, -1):
            gain[i] = -max(-gain[i], gain[i + 1])
        return gain[0]

    # -- 输出 -------------------------------------------------------------

    def __str__(self) -> str:
        lines = ["  +---+---+---+---+---+---+---+---+"]
        for rank in range(7, -1, -1):
            row = "%d |" % (rank + 1)
            for file in range(8):
                piece = self.board[rank * 8 + file]
                row += " %s |" % (PIECE_CHARS[piece] if piece else " ")
            lines.append(row)
            lines.append("  +---+---+---+---+---+---+---+---+")
        lines.append("    a   b   c   d   e   f   g   h")
        side = "白" if self.turn == WHITE else "黑"
        lines.append(f"轮到{side}走  ·  {self.fen()}")
        return "\n".join(lines)


__all__ = [
    "Position", "START_FEN", "VALUE", "PIECE_CHARS", "PIECE_NAMES",
    "encode", "move_from", "move_to", "move_promo", "move_flags", "move_uci",
    "parse_uci", "FLAG_CAPTURE", "FLAG_EP", "FLAG_CASTLE", "FLAG_DOUBLE",
    "CASTLE_WK", "CASTLE_WQ", "CASTLE_BK", "CASTLE_BQ",
]
