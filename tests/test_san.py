"""SAN 记谱与 PGN。"""

import unittest

from caissa.board import Position, parse_uci
from caissa.san import Game, parse_pgn, parse_san, to_san


def internal(fen, uci):
    """把 UCI 文本换成棋盘上的那一个着法（带双步/易位等标记）。"""
    pos = Position(fen)
    raw = parse_uci(uci)
    assert raw is not None, uci
    move = pos.resolve(raw)
    assert move is not None, f"{uci} 在该局面不合法"
    return move


def san_of(fen, uci):
    return to_san(Position(fen), internal(fen, uci))


class ToSanTest(unittest.TestCase):
    def test_pawn_push(self):
        self.assertEqual(san_of(Position().fen(), "e2e4"), "e4")

    def test_pawn_capture(self):
        fen = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"
        self.assertEqual(san_of(fen, "e4d5"), "exd5")

    def test_knight_move(self):
        self.assertEqual(san_of(Position().fen(), "g1f3"), "Nf3")

    def test_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        self.assertEqual(san_of(fen, "e1g1"), "O-O")
        self.assertEqual(san_of(fen, "e1c1"), "O-O-O")

    def test_promotion_with_check(self):
        fen = "7k/P7/8/8/8/8/8/4K3 w - - 0 1"
        self.assertEqual(san_of(fen, "a7a8q"), "a8=Q+")

    def test_promotion_to_knight(self):
        fen = "8/P7/8/8/8/8/8/K6k w - - 0 1"
        self.assertEqual(san_of(fen, "a7a8n"), "a8=N")

    def test_check_marker(self):
        fen = "4k3/8/8/8/8/8/8/4KR2 w - - 0 1"
        self.assertEqual(san_of(fen, "f1f8"), "Rf8+")

    def test_mate_marker(self):
        fen = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
        self.assertEqual(san_of(fen, "a1a8"), "Ra8#")

    def test_file_disambiguation(self):
        # 两个马都能到 e2，按列区分
        fen = "4k3/8/8/8/8/2N5/8/4K1N1 w - - 0 1"
        self.assertEqual(san_of(fen, "c3e2"), "Nce2")
        self.assertEqual(san_of(fen, "g1e2"), "Nge2")

    def test_rank_disambiguation(self):
        # 两个车同在 d 线？改成同一列不同行
        fen = "4k3/8/8/3R4/8/3R4/8/4K3 w - - 0 1"
        self.assertEqual(san_of(fen, "d5d4"), "R5d4")
        self.assertEqual(san_of(fen, "d3d4"), "R3d4")

    def test_both_file_and_rank_needed(self):
        # a1 与 a4 同列、h4 与 a4 同行，两条线索都失效，只能写全
        fen = "4k3/8/8/8/Q6Q/8/8/Q3K3 w - - 0 1"
        self.assertEqual(san_of(fen, "a4d4"), "Qa4d4")

    def test_san_does_not_mutate_position(self):
        pos = Position()
        before = pos.fen()
        to_san(pos, parse_uci("e2e4"))
        self.assertEqual(pos.fen(), before)


class ParseSanTest(unittest.TestCase):
    def test_simple(self):
        move = parse_san(Position(), "e4")
        self.assertEqual(move, internal(Position().fen(), "e2e4"))

    def test_strips_check_and_annotation(self):
        self.assertEqual(parse_san(Position(), "Nf3!?"),
                         internal(Position().fen(), "g1f3"))

    def test_accepts_zero_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        self.assertEqual(parse_san(Position(fen), "0-0"), internal(fen, "e1g1"))
        self.assertEqual(parse_san(Position(fen), "0-0-0"), internal(fen, "e1c1"))

    def test_rejects_illegal(self):
        self.assertIsNone(parse_san(Position(), "e5"))
        self.assertIsNone(parse_san(Position(), "Qd5"))

    def test_accepts_missing_disambiguation(self):
        pos = Position("4k3/8/8/8/8/2N5/8/4K1N1 w - - 0 1")
        # 两个马都能到 e2，宽松解析会拒绝有歧义的写法
        self.assertIsNone(parse_san(pos, "Ne2"))

    def test_promotion_with_equals(self):
        fen = "8/P7/8/8/8/8/8/K6k w - - 0 1"
        self.assertEqual(parse_san(Position(fen), "a8=Q"),
                         internal(fen, "a7a8q"))


class GameTest(unittest.TestCase):
    def test_push_and_pgn(self):
        game = Game(headers={"Event": "Test", "White": "A", "Black": "B"})
        for token in "e4 e5 Nf3 Nc6 Bb5".split():
            self.assertIsNotNone(game.push_san(token), token)
        text = game.pgn()
        self.assertIn('[Event "Test"]', text)
        self.assertIn("1. e4 e5 2. Nf3 Nc6 3. Bb5", text)

    def test_undo_replays(self):
        game = Game()
        for token in "e4 e5 Nf3".split():
            game.push_san(token)
        self.assertTrue(game.undo())
        self.assertEqual(game.moves, ["e4", "e5"])
        self.assertEqual(game.position.fen(),
                         Position("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2").fen())

    def test_status_checkmate(self):
        game = Game()
        for token in "f3 e5 g4 Qh4".split():
            game.push_san(token)
        self.assertEqual(game.status(), "checkmate")
        self.assertEqual(game.moves[-1], "Qh4#")

    def test_legal_san_lists_every_move(self):
        game = Game()
        self.assertEqual(len(game.legal_san()), 20)

    def test_roundtrip_pgn(self):
        game = Game(headers={"Event": "Roundtrip", "Result": "1-0"})
        for token in "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6".split():
            game.push_san(token)
        game.result = "1-0"
        again = parse_pgn(game.pgn())
        self.assertEqual(again.moves, game.moves)
        self.assertEqual(again.result, "1-0")
        self.assertEqual(again.headers.get("Event"), "Roundtrip")


class ParsePgnTest(unittest.TestCase):
    def test_ignores_comments_and_variations(self):
        text = """
[Event "Miniature"]
[Result "0-1"]

1. f3 {слабый ход} e5 2. g4 (2. e4 Nf6) Qh4# 0-1
"""
        game = parse_pgn(text)
        self.assertEqual(game.moves, ["f3", "e5", "g4", "Qh4#"])
        self.assertEqual(game.result, "0-1")
        self.assertEqual(game.status(), "checkmate")

    def test_handles_move_numbers_glued_to_moves(self):
        game = parse_pgn("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6")
        self.assertEqual(len(game.moves), 6)
        self.assertEqual(game.moves[0], "e4")

    def test_stops_at_first_bad_token(self):
        game = parse_pgn("1. e4 e5 2. Qh9 Nc6")
        self.assertEqual(game.moves, ["e4", "e5"])

    def test_custom_start_fen(self):
        text = '''[FEN "4k3/8/8/8/8/8/8/4K2R w K - 0 1"]
[Result "*"]

1. O-O Kd7 *
'''
        game = parse_pgn(text)
        self.assertEqual(game.moves, ["O-O", "Kd7"])
        self.assertEqual(game.headers["FEN"], "4k3/8/8/8/8/8/8/4K2R w K - 0 1")


if __name__ == "__main__":
    unittest.main()
