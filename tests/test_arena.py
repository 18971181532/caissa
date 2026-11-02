"""对局与对抗：结果统计要自洽，棋谱要能重放。"""

import unittest

from caissa.arena import (
    engine_player, match, material_player, play_game, random_player,
)
from caissa.board import Position
from caissa.search import Engine
from caissa.san import parse_pgn


class PlayGameTest(unittest.TestCase):
    def test_random_selfplay_reaches_limit(self):
        record = play_game(random_player, random_player, max_plies=20)
        self.assertEqual(record.plies, 20)
        self.assertEqual(record.result, "*")     # 没下完
        self.assertEqual(len(record.moves), 20)

    def test_record_can_be_replayed(self):
        record = play_game(random_player, random_player, max_plies=30)
        game = parse_pgn("1. " + " ".join(record.moves) + " *")
        self.assertEqual(game.moves, record.moves)

    def test_start_fen(self):
        fen = "4k3/8/8/8/8/8/8/4K2R w - - 0 1"
        record = play_game(random_player, random_player, max_plies=4, start_fen=fen)
        self.assertEqual(record.plies, 4)

    def test_material_beats_random(self):
        result = match(material_player, random_player, games=2, max_plies=50)
        self.assertEqual(result["games"], 2)
        self.assertEqual(result["wins"] + result["draws"] + result["losses"], 2)
        self.assertGreaterEqual(result["score"], 0.5)

    def test_engine_player_returns_legal_move(self):
        engine = Engine(4.0)
        player = engine_player(engine, movetime=0.03)
        pos = Position()
        move = player(pos)
        self.assertIn(move, pos.legal_moves())

    def test_match_counts_are_consistent(self):
        result = match(random_player, random_player, games=2, max_plies=10)
        self.assertEqual(len(result["records"]), 2)
        for record in result["records"]:
            self.assertIn(record.result, ("1-0", "0-1", "1/2-1/2", "*"))

    def test_engine_does_not_lose_to_random(self):
        engine = Engine(4.0)
        result = match(engine_player(engine, depth=2), random_player,
                       games=2, max_plies=80)
        self.assertEqual(result["losses"], 0)


if __name__ == "__main__":
    unittest.main()
