"""搜索：不追求"想得对"，只保证"找到的东西真的成立"。"""

import time
import unittest

from caissa.board import Position, parse_uci
from caissa.eval import MATE
from caissa.search import Engine, Limits, allocate_time


MATE_IN_ONE = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Engine(8.0)

    def setUp(self):
        self.engine.new_game()

    def search(self, fen=START, **kwargs):
        return self.engine.search(Position(fen), Limits(**kwargs))

    def test_finds_mate_in_one(self):
        pos = Position(MATE_IN_ONE)
        result = self.search(MATE_IN_ONE, depth=2)
        self.assertEqual(result.best_move, pos.resolve(parse_uci("a1a8")))
        self.assertGreater(result.score, MATE - 100)

    def test_finds_free_queen(self):
        # 黑后白送，白车一步可吃
        fen = "4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1"
        result = self.search(fen, depth=3)
        self.assertEqual(result.best_move & 63, 4)     # 从 e1 出发
        self.assertEqual((result.best_move >> 6) & 63, 12)   # 落在 e2

    def test_returns_zero_without_legal_moves(self):
        result = self.search("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", depth=2)
        self.assertEqual(result.best_move, 0)
        self.assertEqual(result.pv, [])

    def test_best_move_is_legal(self):
        pos = Position()
        result = self.engine.search(pos, Limits(depth=4))
        self.assertIn(result.best_move, pos.legal_moves())

    def test_pv_is_playable(self):
        pos = Position()
        result = self.engine.search(pos, Limits(depth=4))
        self.assertTrue(result.pv)
        made = []
        for raw in result.pv:
            move = pos.resolve(raw)
            self.assertIsNotNone(move)
            self.assertTrue(pos.make(move))
            made.append(move)
        for move in reversed(made):
            pos.unmake(move)
        self.assertEqual(pos.fen(), Position().fen())

    def test_position_unchanged_after_search(self):
        pos = Position("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
        before = pos.fen()
        self.engine.search(pos, Limits(depth=3))
        self.assertEqual(pos.fen(), before)
        self.assertEqual(len(pos.undo), 0)

    def test_depth_is_reached(self):
        result = self.search(depth=4)
        self.assertGreaterEqual(result.depth, 3)
        self.assertGreater(result.nodes, 100)

    def test_movetime_is_respected(self):
        start = time.perf_counter()
        result = self.search(movetime=0.2)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0)
        self.assertGreater(result.nodes, 0)

    def test_reports_lines(self):
        result = self.search(depth=3)
        self.assertGreaterEqual(len(result.lines), 3)
        self.assertEqual(result.lines[0]["depth"], 1)
        self.assertIn("pv", result.lines[-1])

    def test_stats_counters_exist(self):
        self.search(depth=4)
        for key in ("tt_cutoff", "beta_cutoff", "qnode"):
            self.assertIn(key, self.engine.stats)
        self.assertGreater(self.engine.stats["qnode"], 0)

    def test_new_game_clears_table(self):
        self.search(depth=4)
        before = len(self.engine.tt)
        self.engine.new_game()
        self.assertEqual(len(self.engine.tt), 0)
        self.assertGreaterEqual(before, 0)

    def test_on_depth_callback(self):
        seen = []
        self.engine.search(Position(), Limits(depth=3), on_depth=seen.append)
        self.assertGreaterEqual(len(seen), 3)
        self.assertEqual([row["depth"] for row in seen], list(range(1, len(seen) + 1)))


class TimeTest(unittest.TestCase):
    def test_movetime_wins(self):
        self.assertEqual(allocate_time(Limits(movetime=1.5), 0), 1.5)

    def test_clock_split(self):
        budget = allocate_time(Limits(wtime=60.0, winc=1.0, movestogo=30), 0)
        self.assertGreater(budget, 1.0)
        self.assertLess(budget, 60.0)

    def test_never_uses_more_than_eighty_percent(self):
        budget = allocate_time(Limits(wtime=1.0, movestogo=1), 0)
        self.assertLessEqual(budget, 0.8)

    def test_no_clock_no_budget(self):
        self.assertEqual(allocate_time(Limits(), 0), 0.0)


if __name__ == "__main__":
    unittest.main()
