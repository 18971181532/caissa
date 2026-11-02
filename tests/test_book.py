"""开局库：只保证"给的着法能走"和"路线真的存在"。"""

import unittest

from caissa.board import Position
from caissa.book import LINES, OpeningBook
from caissa.san import parse_pgn


class BookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = OpeningBook()

    def test_has_entries(self):
        self.assertGreater(len(self.book), 100)
        self.assertEqual(len(self.book.lines), len(LINES))

    def test_every_line_is_legal(self):
        for line in LINES:
            pos = Position()
            for token in line.split():
                move = self._move(pos, token)
                self.assertIsNotNone(move, f"{line} 里的 {token} 走不通")
                self.assertTrue(pos.make(move))

    def _move(self, pos, san):
        from caissa.san import parse_san
        return parse_san(pos, san)

    def test_startpos_is_in_book(self):
        move = self.book.pick(Position())
        self.assertIsNotNone(move)
        self.assertIn(move, Position().legal_moves())

    def test_follows_spanish(self):
        pos = Position()
        for token in "e4 e5 Nf3 Nc6 Bb5 a6".split():
            self.assertIn(pos.key, self.book.book, f"{token} 之前的局面不在库里")
            move = self._move(pos, token)
            self.assertIsNotNone(move)
            self.assertTrue(pos.make(move))

    def test_unknown_position_returns_none(self):
        pos = Position("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertIsNone(self.book.pick(pos))

    def test_seed_is_deterministic(self):
        a, b = OpeningBook(seed=7), OpeningBook(seed=7)
        self.assertEqual(a.pick(Position()), b.pick(Position()))

    def test_pgn_export_is_parseable(self):
        text = "[Event \"Book\"]\n\n1. e4 e5 2. Nf3 Nc6 *\n"
        game = parse_pgn(text)
        self.assertEqual(game.moves, ["e4", "e5", "Nf3", "Nc6"])

    @staticmethod
    def _san(pos, move):
        from caissa.san import to_san
        return to_san(pos, move)


if __name__ == "__main__":
    unittest.main()
