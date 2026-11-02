"""HTTP 工作台：路由、状态码、以及"服务端不存状态"这条约定。"""

import json
import threading
import unittest
import urllib.error
import urllib.request

from caissa.server import make_server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3.0)

    # -- 工具 -------------------------------------------------------------

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path):
        try:
            with urllib.request.urlopen(self.url(path), timeout=5) as rsp:
                return rsp.status, rsp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url(path), data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as rsp:
                return rsp.status, json.loads(rsp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    # -- 静态文件 ---------------------------------------------------------

    def test_index(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())
        self.assertIn("Caissa".encode(), body)

    def test_static_assets(self):
        for name in ("/static/app.js", "/static/style.css"):
            status, body = self.get(name)
            self.assertEqual(status, 200, name)
            self.assertTrue(body)

    def test_path_traversal_is_blocked(self):
        status, _ = self.get("/static/../caissa/server.py")
        self.assertIn(status, (403, 404))

    def test_unknown_path(self):
        self.assertEqual(self.get("/nope")[0], 404)

    # -- API --------------------------------------------------------------

    def test_health(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertIn("version", data)

    def test_state(self):
        status, data = self.post("/api/state", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["legal"]), 20)
        self.assertEqual(data["status"], "playing")

    def test_state_accepts_custom_fen(self):
        fen = "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"
        status, data = self.post("/api/state", {"fen": fen})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "checkmate")

    def test_state_rejects_bad_fen(self):
        status, data = self.post("/api/state", {"fen": "garbage"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_move(self):
        status, data = self.post("/api/move", {"move": "e2e4"})
        self.assertEqual(status, 200)
        self.assertEqual(data["san"], "e4")
        self.assertEqual(data["turn"], "b")

    def test_move_by_san(self):
        status, data = self.post("/api/move", {"move": "Nf3"})
        self.assertEqual(status, 200)
        self.assertEqual(data["uci"], "g1f3")

    def test_move_rejects_illegal(self):
        status, data = self.post("/api/move", {"move": "e2e5"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_engine_uses_book_in_opening(self):
        status, data = self.post("/api/engine", {"book": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["book"])
        self.assertTrue(data["best"])

    def test_engine_searches(self):
        status, data = self.post("/api/engine",
                                 {"depth": 2, "book": False, "movetime": 0.3})
        self.assertEqual(status, 200)
        self.assertFalse(data["book"])
        self.assertTrue(data["best"])
        self.assertGreater(data["nodes"], 0)
        self.assertIn("score_text", data)

    def test_engine_on_mate_position(self):
        fen = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
        status, data = self.post("/api/engine",
                                 {"fen": fen, "depth": 2, "book": False,
                                  "movetime": 0.3})
        self.assertEqual(status, 200)
        self.assertEqual(data["best"], "a1a8")
        self.assertIn("#", data["score_text"])

    def test_perft(self):
        status, data = self.post("/api/perft", {"depth": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["nodes"], 400)
        self.assertGreaterEqual(data["seconds"], 0.0)

    def test_unknown_api(self):
        status, data = self.post("/api/nope", {})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_server_keeps_no_state(self):
        # 两次同样的请求必须给出同样的结果
        first = self.post("/api/state", {})[1]
        self.post("/api/move", {"move": "e2e4"})
        second = self.post("/api/state", {})[1]
        self.assertEqual(first["fen"], second["fen"])


if __name__ == "__main__":
    unittest.main()
