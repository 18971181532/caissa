"""perft：棋规实现的硬指标。

深层的参考数字来自 Chess Programming Wiki。这里挑的是"能跑完又不至于让
测试等太久"的层数：完整跑到 5 层要几分钟，不适合放进 CI。
"""

import unittest

from caissa.board import Position
from caissa.perft import SUITE, perft, perft_divide, perft_timed, verify


class PerftTest(unittest.TestCase):
    def test_startpos_first_four_plies(self):
        pos = Position()
        for depth, expected in enumerate(SUITE["startpos"][1][:4], start=1):
            self.assertEqual(perft(pos, depth), expected, f"depth {depth}")

    def test_kiwipete_first_three_plies(self):
        pos = Position(SUITE["kiwipete"][0])
        for depth, expected in enumerate(SUITE["kiwipete"][1][:3], start=1):
            self.assertEqual(perft(pos, depth), expected, f"depth {depth}")

    def test_position3_first_four_plies(self):
        pos = Position(SUITE["position3"][0])
        for depth, expected in enumerate(SUITE["position3"][1][:4], start=1):
            self.assertEqual(perft(pos, depth), expected, f"depth {depth}")

    def test_position4_first_three_plies(self):
        pos = Position(SUITE["position4"][0])
        for depth, expected in enumerate(SUITE["position4"][1][:3], start=1):
            self.assertEqual(perft(pos, depth), expected, f"depth {depth}")

    def test_position5_first_three_plies(self):
        pos = Position(SUITE["position5"][0])
        for depth, expected in enumerate(SUITE["position5"][1][:3], start=1):
            self.assertEqual(perft(pos, depth), expected, f"depth {depth}")

    def test_every_suite_entry_matches_at_depth_two(self):
        for name, (fen, expected) in SUITE.items():
            with self.subTest(position=name):
                self.assertEqual(perft(Position(fen), 2), expected[1])

    def test_divide_sums_to_total(self):
        pos = Position(SUITE["kiwipete"][0])
        rows = perft_divide(pos, 3)
        self.assertEqual(sum(n for _, n in rows), 97862)
        self.assertEqual(len(rows), 48)
        # a1 车被自己的 a2 兵挡住，不该出现在分步表里
        self.assertNotIn("a1a3", dict(rows))

    def test_timed_returns_count_and_seconds(self):
        nodes, seconds = perft_timed(Position(), 3)
        self.assertEqual(nodes, 8902)
        self.assertGreaterEqual(seconds, 0.0)

    def test_verify_reports_all_positions(self):
        rows = verify(max_depth=2)
        self.assertEqual(len(rows), len(SUITE))
        for row in rows:
            self.assertTrue(row["ok"], row)

    def test_position_restored_after_perft(self):
        pos = Position(SUITE["kiwipete"][0])
        before = pos.fen()
        perft(pos, 3)
        self.assertEqual(pos.fen(), before)
        self.assertEqual(len(pos.undo), 0)


if __name__ == "__main__":
    unittest.main()
