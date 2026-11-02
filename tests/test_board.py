"""棋盘：FEN 往返、走子/撤销的可逆性，以及几条容易写错的棋规。"""

import unittest

from caissa.board import (
    FLAG_CAPTURE, Position, move_from, move_flags, move_promo, move_to,
    move_uci, parse_square, parse_uci,
)

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def play(pos, *uci_moves):
    """按 UCI 依次走子，返回走过的内部着法。"""
    made = []
    for text in uci_moves:
        raw = parse_uci(text)
        move = pos.resolve(raw) if raw is not None else None
        assert move is not None, f"非法着法 {text}"
        assert pos.make(move), f"非法着法 {text}"
        made.append(move)
    return made


def ucis(pos):
    return sorted(move_uci(m) for m in pos.legal_moves())


class FenTest(unittest.TestCase):
    def test_start_roundtrip(self):
        self.assertEqual(Position().fen(), START)

    def test_start_has_twenty_moves(self):
        self.assertEqual(len(Position().legal_moves()), 20)

    def test_roundtrip_several_positions(self):
        fens = [
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
            "4k3/8/8/8/8/8/8/4K2R w K - 0 1",
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        ]
        for fen in fens:
            self.assertEqual(Position(fen).fen(), fen)

    def test_reject_broken_fens(self):
        bad = [
            "8/8/8/8/8/8/8 w - - 0 1",                    # 只有 7 行
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBN w KQkq - 0 1",   # 少一列
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNX w KQkq - 0 1",  # 怪字符
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",               # 缺字段
        ]
        for fen in bad:
            with self.assertRaises(ValueError):
                Position(fen)

    def test_castling_rights_pruned_when_rook_missing(self):
        pos = Position("4k3/8/8/8/8/8/8/4K2R w KQ - 0 1")
        self.assertEqual(pos.castling & 3, 1)      # 只剩 K

    def test_fake_en_passant_square_dropped(self):
        # e6 上没有可吃的兵，这个 ep 格是假的
        pos = Position("4k3/8/8/8/8/8/8/4K3 w - e6 0 1")
        self.assertEqual(pos.ep, -1)
        self.assertIn(" - ", pos.fen())


class MakeUnmakeTest(unittest.TestCase):
    def test_key_and_fen_restored_after_every_move(self):
        pos = Position()
        before_fen, before_key = pos.fen(), pos.key
        for move in pos.legal_moves():
            self.assertTrue(pos.make(move))
            pos.unmake(move)
            self.assertEqual(pos.fen(), before_fen)
            self.assertEqual(pos.key, before_key)

    def test_deep_tree_is_reversible(self):
        pos = Position()

        def walk(depth):
            if depth == 0:
                return 0
            count = 0
            for move in pos.generate_moves():
                if not pos.make(move):
                    continue
                count += 1 + walk(depth - 1)
                pos.unmake(move)
            return count

        walk(3)
        self.assertEqual(pos.fen(), START)
        self.assertEqual(len(pos.undo), 0)

    def test_incremental_key_matches_recompute(self):
        pos = Position()
        play(pos, "e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4",
             "g8f6", "b1c3", "a7a6")
        self.assertEqual(pos.key, pos._compute_key())

    def test_resolve_rejects_illegal_move(self):
        pos = Position()
        self.assertIsNone(pos.resolve(parse_uci("e2e5")))
        self.assertIsNone(pos.resolve(parse_uci("a1a8")))
        self.assertEqual(pos.fen(), START)

    def test_turn_flips_twice(self):
        pos = Position()
        play(pos, "e2e4")
        self.assertEqual(pos.turn, 1)
        play(pos, "e7e5")
        self.assertEqual(pos.turn, 0)


class RuleTest(unittest.TestCase):
    def test_en_passant_capture(self):
        pos = Position("rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
        self.assertIn("e5f6", ucis(pos))
        play(pos, "e5f6")
        self.assertEqual(pos.board[parse_square("f5")], 0)   # 被吃的黑兵消失
        self.assertNotEqual(pos.board[parse_square("f6")], 0)

    def test_castling_moves_rook(self):
        pos = Position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        play(pos, "e1g1")
        self.assertEqual(pos.board[7], 0)          # h1 空了
        self.assertEqual(pos.board[5], (0 << 3) | 4)   # f1 是白车

    def test_queenside_castling(self):
        pos = Position("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        play(pos, "e1c1")
        self.assertEqual(pos.board[0], 0)          # a1 空了
        self.assertEqual(pos.board[3], (0 << 3) | 4)   # d1 是白车

    def test_cannot_castle_through_attack(self):
        pos = Position("4k3/8/8/8/8/8/5r2/R3K2R w KQ - 0 1")
        self.assertNotIn("e1g1", ucis(pos))        # f1 被车控制

    def test_cannot_castle_out_of_check(self):
        pos = Position("4k3/8/8/8/8/8/4r3/R3K2R w KQ - 0 1")
        self.assertNotIn("e1g1", ucis(pos))
        self.assertNotIn("e1c1", ucis(pos))

    def test_promotion_produces_four_pieces(self):
        pos = Position("8/P7/8/8/8/8/8/K6k w - - 0 1")
        promos = sorted(move_uci(m) for m in pos.legal_moves()
                        if move_from(m) == parse_square("a7"))
        self.assertEqual(promos, ["a7a8b", "a7a8n", "a7a8q", "a7a8r"])

    def test_promotion_flag_and_piece(self):
        pos = Position("8/P7/8/8/8/8/8/K6k w - - 0 1")
        move = parse_uci("a7a8q")
        play(pos, "a7a8q")
        self.assertEqual(move_promo(move), 5)
        self.assertEqual(pos.board[parse_square("a8")], (0 << 3) | 5)

    def test_only_king_moves_when_pinned(self):
        # 白车 e2 被黑车 e8 牵制，只能沿 e 线走
        pos = Position("4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1")
        for move in pos.legal_moves():
            if move_from(move) == parse_uci("e2"):
                self.assertEqual(move_to(move) & 7, 4)

    def test_check_detection(self):
        pos = Position("4k3/8/8/8/8/8/8/4R1K1 b - - 0 1")
        self.assertTrue(pos.in_check())
        self.assertEqual(pos.checkers().bit_count(), 1)

    def test_checkmate_has_no_moves(self):
        pos = Position("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        self.assertTrue(pos.in_check())
        self.assertFalse(pos.has_legal_move())

    def test_stalemate(self):
        pos = Position("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
        self.assertFalse(pos.in_check())
        self.assertFalse(pos.has_legal_move())

    def test_insufficient_material(self):
        self.assertTrue(Position("4k3/8/8/8/8/8/8/4K3 w - - 0 1").insufficient_material())
        self.assertTrue(Position("4k3/8/8/8/8/8/8/4KB2 w - - 0 1").insufficient_material())
        self.assertFalse(Position("4k3/8/8/8/8/8/8/4KR2 w - - 0 1").insufficient_material())

    def test_halfmove_clock_resets_on_capture(self):
        pos = Position("4k3/8/8/8/8/8/4r3/4R1K1 w - - 17 1")
        play(pos, "e1e2")
        self.assertEqual(pos.halfmove, 0)
        pos2 = Position("4k3/8/8/8/8/8/8/4R1K1 w - - 17 1")
        play(pos2, "e1e2")
        self.assertEqual(pos2.halfmove, 18)

    def test_capture_flag_set(self):
        pos = Position("4k3/8/8/8/8/8/4r3/4R1K1 w - - 0 1")
        move = pos.resolve(parse_uci("e1e2"))
        self.assertIsNotNone(move)
        self.assertTrue(move_flags(move) & FLAG_CAPTURE)

    def test_uci_roundtrip(self):
        for text in ("e2e4", "a7a8q", "e1g1", "b7c8n"):
            move = parse_uci(text)
            self.assertIsNotNone(move)
            self.assertEqual(move_uci(move), text)

    def test_parse_uci_rejects_junk(self):
        for text in ("", "e2", "z9z9", "e2e"):
            self.assertIsNone(parse_uci(text))


class SeeTest(unittest.TestCase):
    def test_free_pawn_is_positive(self):
        pos = Position("4k3/8/8/8/8/8/4p3/4R1K1 w - - 0 1")
        self.assertGreater(pos.see(parse_uci("e1e2")), 0)

    def test_losing_capture_is_negative(self):
        # 车吃有兵保护的象：换子不划算
        pos = Position("4k3/8/8/8/8/2p5/1b6/R3K3 w - - 0 1")
        self.assertLess(pos.see(parse_uci("a1b2")), 0)


if __name__ == "__main__":
    unittest.main()
