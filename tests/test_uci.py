"""UCI 协议：消息顺序与状态转移。

不启动真的 GUI，也不读 stdin——直接喂字符串给 handle()，再检查输出。
"""

import io
import time
import unittest

from caissa.search import Engine
from caissa.uci import UciEngine


class UciTest(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(4.0)
        self.uci = UciEngine(self.engine)
        self.out = io.StringIO()
        self.uci._out = self.out

    def send(self, line):
        return self.uci.handle(line)

    def lines(self):
        return [row for row in self.out.getvalue().splitlines() if row]

    def test_uci_handshake(self):
        self.assertTrue(self.send("uci"))
        body = self.lines()
        self.assertIn("uciok", body)
        self.assertTrue(any(row.startswith("id name ") for row in body))
        self.assertTrue(any(row.startswith("option name Hash") for row in body))

    def test_isready(self):
        self.send("isready")
        self.assertEqual(self.lines(), ["readyok"])

    def test_position_startpos(self):
        self.send("position startpos moves e2e4 e7e5")
        self.assertEqual(self.uci.pos.fen(),
                         "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2")

    def test_position_with_castling(self):
        self.send("position fen r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1 moves e1g1")
        self.assertTrue(self.uci.pos.fen().startswith("r3k2r/8/8/8/8/8/8/R4RK1"))

    def test_bad_move_is_skipped(self):
        self.send("position startpos moves e2e4 e2e4")
        after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        self.assertEqual(self.uci.pos.fen(), after_e4)
        self.assertTrue(any("跳过" in row for row in self.lines()))

    def test_ucinewgame_resets(self):
        self.send("position startpos moves e2e4")
        self.send("ucinewgame")
        self.assertEqual(self.uci.pos.fen(),
                         "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def test_go_depth_returns_bestmove(self):
        self.send("position startpos")
        self.send("go depth 2")
        self.uci._thread.join(timeout=5.0)
        body = self.lines()
        self.assertTrue(any(row.startswith("bestmove ") for row in body), body)
        move = [row for row in body if row.startswith("bestmove ")][-1]
        self.assertRegex(move, r"^bestmove [a-h][1-8][a-h][1-8][nbrq]?( ponder .+)?$")

    def test_go_movetime(self):
        self.send("position startpos")
        start = time.perf_counter()
        self.send("go movetime 100")
        self.uci._thread.join(timeout=5.0)
        self.assertLess(time.perf_counter() - start, 3.0)
        self.assertTrue(any(row.startswith("bestmove ")
                            for row in self.lines()))

    def test_d_prints_board(self):
        self.send("d")
        text = "\n".join(self.lines())
        self.assertIn("a   b   c", text)
        self.assertIn("轮到白走", text)

    def test_eval_command(self):
        self.send("eval")
        self.assertTrue(any(row.startswith("info string 评估")
                            for row in self.lines()))

    def test_perft_command(self):
        self.send("perft 2")
        self.assertTrue(any("perft(2) = 400" in row for row in self.lines()))

    def test_debug_toggles_unknown_warning(self):
        self.send("hello")
        self.assertFalse(any("未识别" in row for row in self.lines()))
        self.send("debug on")
        self.send("hello")
        self.assertTrue(any("未识别" in row for row in self.lines()))

    def test_quit_stops_loop(self):
        self.assertFalse(self.send("quit"))
        self.assertTrue(self.engine.stop)

    def test_setoption_hash(self):
        before = self.engine.tt
        self.send("setoption name Hash value 16")
        self.assertIsNot(self.engine.tt, before)
        # setUp 里是 4 MB，改成 16 MB 之后条数应当变多
        self.assertGreater(self.engine.tt.limit, before.limit)


if __name__ == "__main__":
    unittest.main()
