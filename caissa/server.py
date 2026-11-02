"""本地网页工作台。

不用框架，`http.server` 就够：一个 POST /api/engine 跑一次搜索，一个
POST /api/move 走一步棋，剩下的都是静态文件。服务端不保存对局状态——
客户端每次都把当前 FEN 带上来，刷新页面不会丢，也不需要会话。

这样做的好处是简单；代价是每次请求都要重新解析 FEN（几微秒，可以忽略）。
"""

from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from . import __version__
from .board import Position, START_FEN
from .book import OpeningBook
from .perft import perft
from .service import Coach, status_of

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _num(body: Dict[str, Any], key: str, default: float,
         low: float, high: float) -> float:
    try:
        value = float(body.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


class Workbench:
    """把 Coach 与开局库包成一组可以并发调用的方法。"""

    def __init__(self) -> None:
        self.coach = Coach()
        self.book = OpeningBook()
        self.started = time.time()

    def state(self, body: Dict[str, Any]) -> Dict[str, Any]:
        fen = str(body.get("fen") or START_FEN)[:200]
        try:
            return self.coach.state(fen)
        except ValueError as exc:
            raise ApiError(str(exc))

    def move(self, body: Dict[str, Any]) -> Dict[str, Any]:
        fen = str(body.get("fen") or START_FEN)[:200]
        text = str(body.get("move") or "")[:16]
        try:
            return self.coach.apply(fen, text)
        except ValueError as exc:
            raise ApiError(str(exc))

    def engine(self, body: Dict[str, Any]) -> Dict[str, Any]:
        fen = str(body.get("fen") or START_FEN)[:200]
        depth = int(_num(body, "depth", 0, 0, 20))
        movetime = _num(body, "movetime", 0.0, 0.0, 20.0)
        opening = bool(body.get("book", True))
        try:
            pos = Position(fen)
        except ValueError as exc:
            raise ApiError(str(exc))

        if opening and pos.fullmove <= 10:
            move = self.book.pick(pos)
            if move is not None:
                legal = pos.legal_moves()
                from .san import to_san
                from .board import move_uci
                return {
                    "best": move_uci(move), "best_san": to_san(pos, move, legal),
                    "score": 0, "score_text": "0.00", "depth": 0,
                    "seldepth": 0, "nodes": 0, "qnodes": 0, "nps": 0.0,
                    "time": 0.0, "pv": [], "lines": [], "stats": {},
                    "book": True,
                }
        payload = self.coach.analyze(fen, depth=depth, movetime=movetime)
        payload["book"] = False
        return payload

    def perft(self, body: Dict[str, Any]) -> Dict[str, Any]:
        fen = str(body.get("fen") or START_FEN)[:200]
        depth = int(_num(body, "depth", 3, 1, 6))
        pos = Position(fen)
        t0 = time.perf_counter()
        nodes = perft(pos, depth)
        return {"nodes": nodes, "depth": depth,
                "seconds": time.perf_counter() - t0}


class ApiError(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = f"Caissa/{__version__}"
    workbench: Workbench = None            # type: ignore[assignment]

    # -- 基础 -------------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("CAISSA_HTTP_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 1 << 20))
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    # -- 路由 -------------------------------------------------------------

    def do_GET(self) -> None:                     # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            return self._serve_file("index.html")
        if path.startswith("/static/"):
            return self._serve_file(path[len("/static/"):])
        if path == "/api/health":
            return self._json({
                "ok": True, "version": __version__,
                "uptime": round(time.time() - self.workbench.started, 1),
            })
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:                    # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()
        routes = {
            "/api/state": self.workbench.state,
            "/api/move": self.workbench.move,
            "/api/engine": self.workbench.engine,
            "/api/perft": self.workbench.perft,
        }
        handler = routes.get(path)
        if handler is None:
            return self._json({"error": "未知接口"}, 404)
        try:
            self._json(handler(body))
        except ApiError as exc:
            self._json({"error": str(exc)}, 400)

    def _serve_file(self, name: str) -> None:
        name = name.split("?")[0]
        if "/" in name or "\\" in name or name.startswith("."):
            return self._send(403, b"forbidden", "text/plain; charset=utf-8")
        full = os.path.join(WEB_DIR, name)
        if not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            data = fh.read()
        self._send(200, data, MIME.get(ext, "application/octet-stream"))


def make_server(host: str = "127.0.0.1", port: int = 8790) -> ThreadingHTTPServer:
    Handler.workbench = Workbench()
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def serve(host: str = "127.0.0.1", port: int = 8790,
          open_browser: bool = True) -> int:
    httpd = make_server(host, port)
    url = f"http://{host}:{port}/"
    print(f"Caissa 工作台已启动：{url}")
    print("按 Ctrl+C 停止。")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        httpd.server_close()
    return 0


__all__ = ["serve", "make_server", "Handler", "Workbench"]
