"""攻击表：落点集合必须与"手数格子"完全一致。"""

import unittest

from caissa.attacks import (
    BISHOP, KING_ATTACKS, KNIGHT_ATTACKS, PAWN_ATTACKS, QUEEN, ROOK,
    bishop_attacks, name_of, parse_square, queen_attacks, rook_attacks, square,
)


def bits(bb):
    out = []
    while bb:
        bit = bb & -bb
        out.append(bit.bit_length() - 1)
        bb ^= bit
    return out


def names(bb):
    return sorted(name_of(sq) for sq in bits(bb))


class SquareTest(unittest.TestCase):
    def test_roundtrip_all_squares(self):
        for sq in range(64):
            self.assertEqual(parse_square(name_of(sq)), sq)

    def test_corners(self):
        self.assertEqual(parse_square("a1"), 0)
        self.assertEqual(parse_square("h1"), 7)
        self.assertEqual(parse_square("a8"), 56)
        self.assertEqual(parse_square("h8"), 63)
        self.assertEqual(square(4, 3), parse_square("e4"))

    def test_reject_bad_names(self):
        for text in ("", "e", "e9", "i4", "44"):
            with self.assertRaises(ValueError):
                parse_square(text)


class LeaperTest(unittest.TestCase):
    def test_knight_center_has_eight_targets(self):
        self.assertEqual(len(bits(KNIGHT_ATTACKS[parse_square("d4")])), 8)

    def test_knight_corner_has_two_targets(self):
        self.assertEqual(names(KNIGHT_ATTACKS[parse_square("a1")]),
                         ["b3", "c2"])

    def test_king_center_has_eight_targets(self):
        self.assertEqual(len(bits(KING_ATTACKS[parse_square("e5")])), 8)

    def test_king_corner_has_three_targets(self):
        self.assertEqual(len(bits(KING_ATTACKS[parse_square("h8")])), 3)

    def test_pawns_capture_forward_only(self):
        self.assertEqual(names(PAWN_ATTACKS[0][parse_square("e4")]),
                         ["d5", "f5"])
        self.assertEqual(names(PAWN_ATTACKS[1][parse_square("e4")]),
                         ["d3", "f3"])


class SliderTest(unittest.TestCase):
    def test_empty_board_counts(self):
        d4 = parse_square("d4")
        self.assertEqual(len(bits(bishop_attacks(d4, 0))), 13)
        self.assertEqual(len(bits(rook_attacks(d4, 0))), 14)
        self.assertEqual(len(bits(queen_attacks(d4, 0))), 27)

    def test_rook_stops_at_first_blocker(self):
        a1 = parse_square("a1")
        occ = 1 << parse_square("a4")
        attacks = names(rook_attacks(a1, occ))
        # 竖直方向到 a4 为止（含 a4），横向整条第一横线
        self.assertIn("a4", attacks)
        self.assertNotIn("a5", attacks)
        self.assertEqual(len([n for n in attacks if n[0] == "a"]), 3)

    def test_bishop_blocked_by_two_pieces(self):
        d4 = parse_square("d4")
        occ = (1 << parse_square("f6")) | (1 << parse_square("b2"))
        attacks = names(bishop_attacks(d4, occ))
        self.assertIn("f6", attacks)
        self.assertNotIn("g7", attacks)
        self.assertIn("b2", attacks)
        self.assertNotIn("a1", attacks)

    def test_queen_is_union(self):
        sq = parse_square("c3")
        occ = (1 << parse_square("c6")) | (1 << parse_square("f6"))
        self.assertEqual(queen_attacks(sq, occ),
                         bishop_attacks(sq, occ) | rook_attacks(sq, occ))

    def test_edge_square_ray_counts(self):
        # 角上的车：横向 7 + 纵向 7
        self.assertEqual(len(bits(rook_attacks(parse_square("h1"), 0))), 14)
        # 角上的象：只有一条对角线
        self.assertEqual(len(bits(bishop_attacks(parse_square("h1"), 0))), 7)


if __name__ == "__main__":
    unittest.main()
