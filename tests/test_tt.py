"""置换表：命中、覆盖策略、容量上限。"""

import unittest

from caissa.tt import EXACT, LOWER, TranspositionTable


class TableTest(unittest.TestCase):
    def setUp(self):
        self.tt = TranspositionTable(1.0)

    def test_store_and_probe(self):
        self.tt.store(12345, 5, 42, EXACT, 999)
        self.assertEqual(self.tt.probe(12345), (5, 42, EXACT, 999))

    def test_miss_returns_none(self):
        self.assertIsNone(self.tt.probe(1))
        self.assertEqual(self.tt.probes, 1)
        self.assertEqual(self.tt.hits, 0)

    def test_deeper_entry_wins(self):
        self.tt.store(7, 6, 10, EXACT, 100)
        self.tt.store(7, 2, -50, LOWER, 200)
        self.assertEqual(self.tt.probe(7), (6, 10, EXACT, 100))

    def test_shallower_entry_is_replaced_when_no_move(self):
        self.tt.store(7, 6, 10, EXACT, 0)
        self.tt.store(7, 2, -50, LOWER, 200)
        self.assertEqual(self.tt.probe(7), (2, -50, LOWER, 200))

    def test_same_depth_overwrites(self):
        self.tt.store(7, 3, 10, EXACT, 100)
        self.tt.store(7, 3, 20, LOWER, 101)
        self.assertEqual(self.tt.probe(7), (3, 20, LOWER, 101))

    def test_clear_resets_everything(self):
        self.tt.store(1, 1, 1, EXACT, 1)
        self.tt.probe(1)
        self.tt.clear()
        self.assertEqual(len(self.tt), 0)
        self.assertEqual((self.tt.probes, self.tt.hits, self.tt.stores), (0, 0, 0))

    def test_fill_ratio(self):
        self.assertEqual(self.tt.fill, 0.0)
        self.tt.store(1, 1, 1, EXACT, 1)
        self.assertAlmostEqual(self.tt.fill, 1 / self.tt.limit)

    def test_capacity_is_bounded(self):
        small = TranspositionTable(0.0)          # 至少 1024 条
        self.assertEqual(small.limit, 1024)
        for key in range(1100):
            small.store(key, 1, 0, EXACT, 1)
        self.assertLessEqual(len(small), small.limit)


if __name__ == "__main__":
    unittest.main()
