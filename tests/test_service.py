"""门面：CLI 与网页都只走这里，所以它的返回结构必须稳。"""

import unittest

from caissa.board import Position
from caissa.eval import MATE
from caissa.service import Coach, pv_san, score_text, status_of


class StateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coach = Coach()

    def test_start_position(self):
        state = self.coach.state()
        self.assertEqual(len(state["legal"]), 20)
        self.assertEqual(state["turn"], "w")
        self.assertEqual(state["status"], "playing")
        self.assertFalse(state["check"])
        self.assertEqual(state["fullmove"], 1)
        self.assertIsInstance(state["detail"], dict)

    def test_checkmate_state(self):
        state = self.coach.state("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
        self.assertEqual(state["status"], "checkmate")
        self.assertEqual(state["status_text"], "将杀")
        self.assertTrue(state["check"])
        self.assertEqual(state["legal"], [])

    def test_stalemate_state(self):
        state = self.coach.state("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")
        self.assertEqual(state["status"], "stalemate")

    def test_legal_entries_have_both_notations(self):
        state = self.coach.state()
        for entry in state["legal"]:
            self.assertRegex(entry["uci"], r"^[a-h][1-8][a-h][1-8][nbrq]?$")
            self.assertTrue(entry["san"])


class ApplyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coach = Coach()

    def test_uci_move(self):
        state = self.coach.apply(Position().fen(), "e2e4")
        self.assertEqual(state["san"], "e4")
        self.assertEqual(state["uci"], "e2e4")
        self.assertEqual(state["turn"], "b")

    def test_san_move(self):
        state = self.coach.apply(Position().fen(), "Nf3")
        self.assertEqual(state["uci"], "g1f3")

    def test_castling_actually_moves_rook(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        state = self.coach.apply(fen, "e1g1")
        self.assertEqual(state["san"], "O-O")
        self.assertTrue(state["fen"].startswith("r3k2r/8/8/8/8/8/8/R4RK1"))

    def test_en_passant_removes_pawn(self):
        fen = "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3"
        state = self.coach.apply(fen, "e5f6")
        self.assertTrue(state["fen"].startswith("rnbqkbnr/ppp1p1pp/5P2"))

    def test_illegal_move_raises(self):
        with self.assertRaises(ValueError):
            self.coach.apply(Position().fen(), "e2e5")
        with self.assertRaises(ValueError):
            self.coach.apply(Position().fen(), "Qd5")

    def test_bad_fen_raises(self):
        with self.assertRaises(ValueError):
            self.coach.state("不是 FEN")


class AnalyzeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.coach = Coach()

    def test_depth_search(self):
        result = self.coach.analyze(depth=3)
        self.assertTrue(result["best"])
        self.assertTrue(result["best_san"])
        self.assertGreaterEqual(result["depth"], 2)
        self.assertGreater(result["nodes"], 0)
        self.assertTrue(result["pv"])
        self.assertIn("stats", result)

    def test_movetime_search(self):
        result = self.coach.analyze(movetime=0.15)
        self.assertLess(result["time"], 2.0)
        self.assertGreater(result["nodes"], 0)

    def test_finds_mate(self):
        result = self.coach.analyze("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", depth=2)
        self.assertEqual(result["best"], "a1a8")
        self.assertIn("#", result["score_text"])
        self.assertEqual(result["best_san"], "Ra8#")

    def test_lines_have_san_pv(self):
        result = self.coach.analyze(depth=3)
        self.assertTrue(result["lines"])
        first = result["lines"][0]
        self.assertEqual(first["depth"], 1)
        self.assertTrue(first["pv"])

    def test_last_is_cached(self):
        result = self.coach.analyze(depth=2)
        self.assertIs(self.coach.last, result)


class HelperTest(unittest.TestCase):
    def test_status_of(self):
        self.assertEqual(status_of(Position()), "playing")
        self.assertEqual(status_of(Position("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")),
                         "checkmate")
        self.assertEqual(status_of(Position("7k/5Q2/7K/8/8/8/8/8 b - - 0 1")),
                         "stalemate")

    def test_score_text(self):
        self.assertEqual(score_text(0), "+0.00")
        self.assertEqual(score_text(35), "+0.35")
        self.assertEqual(score_text(MATE - 1), "#1")
        self.assertEqual(score_text(-MATE + 3), "−#2")

    def test_pv_san_resolves_plain_uci(self):
        from caissa.board import parse_uci
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        pos = Position(fen)
        self.assertEqual(pv_san(pos, [parse_uci("e1g1")]), ["O-O"])
        self.assertEqual(pv_san(pos, [parse_uci("e1c1")]), ["O-O-O"])
        black = "r3k2r/8/8/8/8/8/8/4K3 b kq - 0 1"
        self.assertEqual(pv_san(Position(black), [parse_uci("e8g8")]), ["O-O"])
        # 走完要复原
        self.assertEqual(pos.fen(), fen)

    def test_pv_stops_at_bad_move(self):
        pos = Position()
        self.assertEqual(pv_san(pos, [0, 0]), [])


if __name__ == "__main__":
    unittest.main()
