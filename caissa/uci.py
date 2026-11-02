"""UCI 协议。

实现了 GUI 用得上的那部分：``uci`` ``isready`` ``ucinewgame`` ``position``
``go`` ``stop`` ``ponderhit`` ``quit``，外加几个自己调试用的 ``d`` ``eval``
``perft``。搜索跑在单独线程里，所以 ``stop`` 能在思考途中生效。

协议本身没有"请求-响应"的配对机制，只有两处硬约定：收到 ``uci`` 要回
``uciok``，收到 ``isready`` 要回 ``readyok``。其余都是异步的通知。
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Dict, List, Optional, TextIO

from .board import Position, move_uci, parse_uci
from .eval import evaluate, format_score
from .perft import perft_divide
from .search import Engine, Limits, SearchResult

START = "uciok"


class UciEngine:
    def __init__(self, engine: Optional[Engine] = None, book=None):
        self.engine = engine or Engine()
        self.book = book
        self.pos = Position()
        self.name = "Caissa 1.0"
        self.author = "遥か"
        self.debug = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._out: TextIO = sys.stdout

    # -- 输出 -------------------------------------------------------------

    def send(self, text: str) -> None:
        with self._lock:
            print(text, file=self._out, flush=True)

    def info(self, text: str) -> None:
        self.send("info string " + text)

    # -- 主循环 -----------------------------------------------------------

    def loop(self, stream: Optional[TextIO] = None) -> None:
        src = stream or sys.stdin
        for raw in src:
            line = raw.strip()
            if not line:
                continue
            if not self.handle(line):
                break
        self.engine.stop = True

    def handle(self, line: str) -> bool:
        tokens = line.split()
        cmd = tokens[0]
        args = tokens[1:]

        if cmd == "uci":
            self.send(f"id name {self.name}")
            self.send(f"id author {self.author}")
            self.send("option name Hash type spin default 32 min 1 max 1024")
            self.send("option name Threads type spin default 1 min 1 max 1")
            self.send("uciok")
        elif cmd == "isready":
            self.send("readyok")
        elif cmd == "ucinewgame":
            self.engine.new_game()
            self.pos = Position()
        elif cmd == "position":
            self.cmd_position(args)
        elif cmd == "go":
            self.cmd_go(args)
        elif cmd == "stop":
            self.engine.stop = True
        elif cmd == "ponderhit":
            pass
        elif cmd == "quit":
            self.engine.stop = True
            return False
        elif cmd == "d":
            self.send(str(self.pos).replace("\n", "\ninfo string "))
        elif cmd == "eval":
            detail: Dict[str, int] = {}
            score = evaluate(self.pos, detail)
            self.info(f"评估 {format_score(score)}  " +
                      "  ".join(f"{k}={v}" for k, v in detail.items()))
        elif cmd == "perft":
            depth = int(args[0]) if args else 4
            t0 = time.perf_counter()
            rows = perft_divide(self.pos, depth)
            total = sum(n for _, n in rows)
            elapsed = time.perf_counter() - t0
            for name, n in rows[:12]:
                self.info(f"{name}: {n}")
            self.info(f"perft({depth}) = {total}  节点/秒 {total / elapsed:,.0f}")
        elif cmd == "setoption":
            self.cmd_setoption(args)
        elif cmd == "debug":
            self.debug = bool(args and args[0] == "on")
        else:
            if self.debug:
                self.info(f"未识别的命令：{line}")
        return True

    # -- 命令实现 ---------------------------------------------------------

    def cmd_position(self, args: List[str]) -> None:
        if not args:
            return
        if args[0] == "startpos":
            self.pos = Position()
            rest = args[1:]
        elif args[0] == "fen":
            try:
                cut = args.index("moves")
            except ValueError:
                cut = len(args)
            self.pos = Position(" ".join(args[1:cut]))
            rest = args[cut:]
        else:
            return
        if rest and rest[0] == "moves":
            for token in rest[1:]:
                raw = parse_uci(token)
                move = self.pos.resolve(raw) if raw is not None else None
                if move is None or not self.pos.make(move):
                    self.info(f"跳过了不合法的着法：{token}")
                    break
        self.engine.prev_score = None

    def cmd_go(self, args: List[str]) -> None:
        pairs: Dict[str, str] = {}
        key = None
        for token in args:
            if token in ("wtime", "btime", "winc", "binc", "movestogo", "depth",
                         "nodes", "movetime", "mate", "infinite"):
                key = token
                pairs[key] = "1" if key in ("infinite", "mate") else "0"
            elif key is not None:
                pairs[key] = token
                key = None
        limits = Limits.from_uci(pairs)
        if "infinite" in pairs or "mate" in pairs:
            limits.depth = limits.depth or 64
            limits.movetime = 0.0

        if self.book is not None and limits.depth >= 8 and self.pos.fullmove <= 12:
            book_move = self.book.pick(self.pos)
            if book_move is not None:
                self.send(f"info string book {move_uci(book_move)}")
                self.send(f"bestmove {move_uci(book_move)}")
                return

        snapshot = self.pos.clone()
        self.engine.stop = False
        self._thread = threading.Thread(target=self._search, args=(snapshot, limits),
                                        daemon=True)
        self._thread.start()

    def _search(self, pos: Position, limits: Limits) -> None:
        def on_depth(line: Dict[str, object]) -> None:
            score = line["score"]
            if abs(score) > 31000:
                bound = "mate " + str((32000 - abs(score) + 1) // 2)
                score_text = f"score {bound}"
            else:
                score_text = f"score cp {score}"
            pv = " ".join(line["pv"])          # type: ignore[arg-type]
            self.send("info depth %d seldepth %d %s nodes %d nps %d time %d pv %s" % (
                line["depth"], line["seldepth"], score_text, line["nodes"],
                int(line["nps"]), int(float(line["time"]) * 1000), pv))

        result = self.engine.search(pos, limits, on_depth=on_depth)
        self.send(f"bestmove {move_uci(result.best_move)}")

    def cmd_setoption(self, args: List[str]) -> None:
        # setoption name Hash value 128
        if "name" not in args or "value" not in args:
            return
        name = " ".join(args[args.index("name") + 1:args.index("value")]).lower()
        value = args[args.index("value") + 1]
        if name == "hash":
            try:
                self.engine.tt = type(self.engine.tt)(float(value))
            except ValueError:
                pass


def main(argv: Optional[List[str]] = None) -> int:
    engine = UciEngine()
    engine.loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
