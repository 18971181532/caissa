"""评估函数：符号、对称性、以及几个"人一眼能看出来"的局面。"""

import unittest

from caissa.board import Position
from caissa.eval import MATE, evaluate, format_score


class EvalTest(unittest.TestCase):
    def test_startpos_is_nearly_equal(self):
        # 只有 tempo 的 10 厘兵
        self.assertLessEqual(abs(evaluate(Position())), 20)

    def test_extra_queen_is_winning(self):
        pos = Position("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        self.assertGreater(evaluate(pos), 800)

    def test_extra_rook_is_winning(self):
        white_up = Position("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        self.assertGreater(evaluate(white_up), 400)

    def test_perspective_follows_side_to_move(self):
        fen = "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"
        white = evaluate(Position(fen))
        black = evaluate(Position(fen.replace(" w ", " b ")))
        # 同一局面，换一方走，分数应当近似互为相反数（差一个 tempo）
        self.assertAlmostEqual(white + black, 20, delta=1)

    def test_side_to_move_only_changes_tempo(self):
        # 同一局面换一方走，只有 tempo 的差别
        white = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
        black = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R b KQkq - 0 1"
        self.assertAlmostEqual(evaluate(Position(white)),
                               evaluate(Position(black)), delta=20)

    def test_passed_pawn_is_bonus(self):
        base = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        with_pawn = "4k3/8/8/8/8/4P3/8/4K3 w - - 0 1"
        self.assertGreater(evaluate(Position(with_pawn)),
                           evaluate(Position(base)))

    def test_doubled_pawns_are_penalised(self):
        # 同样是两个兵：一个叠在 e 线，一个分在 d/e 两线
        doubled = "4k3/8/8/8/8/4P3/4P3/4K3 w - - 0 1"
        spread = "4k3/8/8/8/8/4P3/3P4/4K3 w - - 0 1"
        self.assertGreater(evaluate(Position(spread)),
                           evaluate(Position(doubled)))

    def test_detail_is_filled(self):
        detail = {}
        evaluate(Position("4k3/8/8/8/8/8/8/3QK3 w - - 0 1"), detail)
        for key in ("material", "mg", "eg", "phase"):
            self.assertIn(key, detail)
        self.assertGreater(detail["material"], 800)

    def test_phase_shrinks_with_fewer_pieces(self):
        full = {}
        bare = {}
        evaluate(Position(), full)
        evaluate(Position("4k3/8/8/8/8/8/8/3QK3 w - - 0 1"), bare)
        self.assertGreater(full["phase"], bare["phase"])


class FormatTest(unittest.TestCase):
    def test_pawns(self):
        self.assertEqual(format_score(0), "+0.00")
        self.assertEqual(format_score(35), "+0.35")
        self.assertEqual(format_score(-120), "-1.20")

    def test_mate(self):
        self.assertEqual(format_score(MATE - 1), "#")
        self.assertEqual(format_score(-MATE + 1), "#-")


if __name__ == "__main__":
    unittest.main()
