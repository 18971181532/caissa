"""命令行入口。

    python -m caissa play          # 终端里跟引擎下棋
    python -m caissa search --depth 8
    python -m caissa perft
    python -m caissa arena --games 20
    python -m caissa serve
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional

from .arena import engine_player, match, material_player, random_player
from .board import Position, START_FEN, VALUE, move_uci, parse_uci
from .book import OpeningBook
from .console import (
    BOLD, CYAN, DIM, GREEN, RED, YELLOW, force_utf8, ljust, paint, rjust, rule,
    supports_unicode,
)
from .eval import MATE, evaluate, format_score
from .perft import SUITE, perft, perft_divide, verify
from .san import Game, parse_pgn, parse_san, to_san
from .search import Engine, Limits
from .service import Coach, score_text, status_of

UNICODE_PIECES = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}
ASCII_PIECES = {c: c for c in "KQRBNPkqrbnp"}


def _chars() -> Dict[str, str]:
    return UNICODE_PIECES if supports_unicode() else ASCII_PIECES


def render_board(pos: Position, flip: bool = False, last: Optional[int] = None,
                 show_coords: bool = True) -> str:
    """画棋盘。宽字符版本每格 3 列，ASCII 版本每格 2 列。"""
    from .board import PIECE_CHARS

    chars = _chars()
    wide = supports_unicode()
    cell = 3 if wide else 2
    plain = bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()

    ranks = list(range(1, 9)) if flip else list(range(8, 0, -1))
    files = list(range(7, -1, -1)) if flip else list(range(8))

    def cell_text(sq: int) -> str:
        piece = pos.board[sq]
        letter = PIECE_CHARS[piece] if piece else ""
        text = chars.get(letter, " ") if letter else (" " if wide else ".")
        dark = ((sq >> 3) + (sq & 7)) % 2 == 0
        if plain:
            return f"{text:^{cell}}"
        bg = "\033[48;5;180m" if dark else "\033[48;5;223m"
        if sq == last:
            bg = "\033[48;5;150m"
        return f"{bg}{text:^{cell}}\033[0m"

    lines: List[str] = []
    label = "   " + "".join(
        " " + ("abcdefgh"[f].center(cell - 1)) for f in files)
    if show_coords:
        lines.append(paint(label, DIM))
    lines.append(paint("  ┌" + "┬".join("─" * cell for _ in files) + "┐", DIM))
    for i, rank in enumerate(ranks):
        row = (f"{rank} │" if show_coords else "│")
        row += "│".join(cell_text(rank * 8 - 8 + f) for f in files)
        row += "│" + (f" {rank}" if show_coords else "")
        lines.append(row)
        lines.append(paint(("  └" if i == len(ranks) - 1 else "  ├")
                           + ("┴" if i == len(ranks) - 1 else "┼").join(
                               "─" * cell for _ in files)
                           + ("┘" if i == len(ranks) - 1 else "┤"), DIM))
    if show_coords:
        lines.append(paint(label, DIM))
    return "\n".join(lines)


def board_line(pos: Position) -> str:
    side = "白" if pos.turn == 0 else "黑"
    bits = [f"轮到{side}方"]
    if pos.in_check():
        bits.append(paint("将军", RED))
    status = status_of(pos)
    if status != "playing":
        bits.append(paint({"checkmate": "将杀", "stalemate": "逼和",
                           "draw": "和棋"}[status], YELLOW))
    detail: Dict[str, int] = {}
    cp = evaluate(pos, detail)
    bits.append("评估 #" if status == "checkmate" else f"评估 {format_score(cp)}")
    bits.append(paint(f"半回合 {pos.halfmove}", DIM))
    return "  ·  ".join(bits)


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------

def cmd_search(args) -> int:
    coach = Coach()
    fen = args.fen or START_FEN
    t0 = time.perf_counter()
    result = coach.analyze(fen, depth=args.depth, movetime=args.movetime)
    elapsed = time.perf_counter() - t0

    pos = Position(fen)
    print(render_board(pos, flip=args.flip))
    print(board_line(pos))
    print()
    print(paint(f"搜索完成  {result['depth']} 层 / 选择深度 {result['seldepth']}", BOLD))
    print(paint(rule(74), DIM))
    print(f"{rjust('层', 3)}  {rjust('分数', 8)}  {rjust('节点', 10)}  "
          f"{rjust('用时', 7)}  {rjust('节点/秒', 10)}  主变")
    for line in result["lines"]:
        print(f"{line['depth']:>3}  {rjust(line['score_text'], 8)}  "
              f"{line['nodes']:>10,}  {line['time']:>6.2f}s  "
              f"{line['nps'] / 1000:>9.0f}k  " + " ".join(line["pv"][:8]))
    print(paint(rule(74), DIM))
    print(f"最佳着法 {paint(result['best_san'] + ' (' + result['best'] + ')', GREEN)}"
          f"   {score_text(result['score'])}")
    print(f"节点 {result['nodes']:,} + 静态搜索 {result['qnodes']:,}"
          f"  ·  {result['nps'] / 1000:.0f}k 节点/秒  ·  总用时 {elapsed:.2f}s")
    stats = result["stats"]
    print(paint(f"剪枝：置换表命中 {stats['tt_cutoff']:,}  ·  空着剪枝 {stats['null_cutoff']:,}"
                f"  ·  削减 {stats['lmr']:,}（重搜 {stats['lmr_research']:,}）"
                f"  ·  beta 截断 {stats['beta_cutoff']:,}", DIM))
    return 0


def cmd_eval(args) -> int:
    pos = Position(args.fen or START_FEN)
    detail: Dict[str, int] = {}
    cp = evaluate(pos, detail)
    print(render_board(pos, flip=args.flip))
    print()
    print(paint("评估（白方视角，厘兵）", BOLD))
    print(paint(rule(46), DIM))
    labels = [("material", "材料 + 位置表"), ("pawns", "兵形"), ("pieces", "象对 / 车线"),
              ("shield", "王前兵盾"), ("mobility", "机动性")]
    for key, label in labels:
        value = detail.get(key, 0)
        bar = " " * 20
        if value:
            width = min(20, abs(value) // 12 + 1)
            bar = (" " * (20 - width) + "█" * width) if value > 0 else \
                  ("█" * width + " " * (20 - width))
        print(f"{label:<12} {value:>+6}  {paint(bar, GREEN if value > 0 else RED)}")
    print(paint(rule(46), DIM))
    phase = detail.get("phase", 0)
    print(f"{'中局分':<12} {detail.get('mg', 0):>+6}")
    print(f"{'残局分':<12} {detail.get('eg', 0):>+6}")
    print(f"{'阶段':<12} {phase:>5}/24  " + paint("（24 = 开局，0 = 残局）", DIM))
    print(paint(rule(46), DIM))
    print(f"合计 {paint(format_score(cp), BOLD)}（轮到走棋方）")
    return 0


def cmd_perft(args) -> int:
    if args.fen:
        pos = Position(args.fen)
        print(render_board(pos))
        for depth in range(1, args.depth + 1):
            t0 = time.perf_counter()
            n = perft(pos, depth)
            dt = time.perf_counter() - t0
            print(f"perft({depth}) = {n:>12,}   {dt:>7.2f}s   {n / dt:>10,.0f} 节点/秒")
        if args.divide:
            print()
            for name, n in perft_divide(pos, args.depth)[:20]:
                print(f"  {name}  {n:,}")
        return 0

    print(paint(f"{ljust('局面', 12)}{rjust('深度', 6)}{rjust('节点', 14)}"
                f"{rjust('参考值', 14)}{rjust('结果', 6)}{rjust('用时', 9)}"
                f"{rjust('节点/秒', 11)}", BOLD))
    print(paint(rule(80), DIM))
    total_ok = 0
    rows = verify(max_depth=args.depth)
    for row in rows:
        ok = paint("通过", GREEN) if row["ok"] else paint("不符", RED)
        print(f"{row['name']:<12}{row['depth']:>6}{row['got']:>14,}"
              f"{row['want']:>14,}{rjust(ok, 6)}{row['seconds']:>8.2f}s"
              f"{row['nps']:>11,.0f}")
        total_ok += bool(row["ok"])
    print(paint(rule(80), DIM))
    verdict = paint("全部通过", GREEN) if total_ok == len(rows) else paint("有失败", RED)
    print(f"{total_ok}/{len(rows)} 个标准局面与参考值一致 —— {verdict}")
    return 0 if total_ok == len(rows) else 1


def cmd_arena(args) -> int:
    engine = Engine(megabytes=args.hash)
    ours = engine_player(engine, movetime=args.movetime)
    opponents = {"random": random_player, "material": material_player}
    name = args.vs
    opponent = opponents[name]

    def progress(i, record, w, d, l):
        mark = {"1-0": "1-0", "0-1": "0-1"}.get(record.result, "和")
        print(f"  第 {i + 1:>2} 局  {mark:<4} {record.plies:>3} 回合  {record.reason}"
              f"   当前 {w}-{d}-{l}", flush=True)

    print(f"对手：{name}  ·  {args.games} 局  ·  每步 {args.movetime * 1000:.0f} ms")
    print(paint(rule(64), DIM))
    result = match(ours, opponent, games=args.games, max_plies=args.max_plies,
                   on_game=progress)
    print(paint(rule(64), DIM))
    print(f"战绩 {result['wins']}-{result['draws']}-{result['losses']}"
          f"   得分率 {result['score'] * 100:.0f}%")
    if result["elo"] != float("inf"):
        print(f"Elo 差 {result['elo']:+.0f}"
              f"（95% 区间 {result['elo_low']:+.0f} … {result['elo_high']:+.0f}）")
    return 0


def cmd_pgn(args) -> int:
    text = open(args.input, encoding=args.encoding).read()
    game = parse_pgn(text)
    print(paint(f"{len(game.moves)} 个着法 · {(len(game.moves) + 1) // 2} 回合", BOLD))
    print(" ".join(f"{i // 2 + 1}.{m}" if i % 2 == 0 else m
                   for i, m in enumerate(game.moves))[:600])
    print()
    print(render_board(game.position))
    print(board_line(game.position))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(game.pgn())
        print(f"已写入 {args.out}")
    return 0


def cmd_board(args) -> int:
    pos = Position(args.fen or START_FEN)
    print(render_board(pos, flip=args.flip))
    print(board_line(pos))
    return 0


def cmd_play(args) -> int:
    coach = Coach()
    engine = coach.engine
    book = OpeningBook()
    pos = Position(args.fen or START_FEN)
    human = 0 if args.color in ("w", "white") else 1
    level = args.level
    history: List[int] = []
    last: Optional[int] = None

    print(paint("Caissa —— 输入 SAN 或 UCI 走法，如 e4 / Nf3 / e2e4", DIM))
    print(paint("命令：undo 悔棋 · hint 提示 · new 新局 · fen 局面 · level N 难度 · quit 退出", DIM))
    print()

    while True:
        print(render_board(pos, flip=(human == 1), last=last))
        print(board_line(pos))
        status = status_of(pos)
        if status != "playing":
            won = status == "checkmate" and pos.turn != human
            print()
            print(paint("你赢了。" if won else "对局结束。", GREEN if won else YELLOW))
            break
        print()

        if pos.turn != human:
            t0 = time.perf_counter()
            result = engine.search(pos, Limits(depth=level))
            dt = time.perf_counter() - t0
            move = result.best_move
            san = to_san(pos, move)
            print(paint(f"引擎：{san}   {score_text(result.score)}   "
                        f"{result.depth} 层 / {result.nodes:,} 节点 / {dt:.2f}s", CYAN))
            pos.make(move)
            history.append(move)
            last = move
            continue

        try:
            line = input(paint("你走 > ", BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        low = line.lower()
        if low in ("quit", "exit", "q"):
            break
        if low == "undo":
            for _ in range(2):
                if history:
                    move = history.pop()
                    pos.unmake(move)
                    last = history[-1] if history else None
            continue
        if low == "new":
            pos = Position()
            history.clear()
            last = None
            continue
        if low == "fen":
            print(pos.fen())
            continue
        if low.startswith("level"):
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                level = max(1, min(10, int(parts[1])))
            print(f"难度：{level} 层")
            continue
        if low == "hint":
            result = engine.search(pos.clone(), Limits(depth=min(8, level + 2)))
            print(paint(f"建议 {to_san(pos, result.best_move)}  {score_text(result.score)}", YELLOW))
            continue

        raw = parse_uci(line)
        move = pos.resolve(raw) if raw is not None else None
        if move is None:
            move = parse_san(pos, line)
        if move is None:
            print(paint("看不懂这步棋。", RED))
            continue
        san = to_san(pos, move)
        pos.make(move)
        history.append(move)
        last = move
        print(paint(f"你：{san}", DIM))
    return 0


def cmd_book(args) -> int:
    book = OpeningBook()
    print(f"开局库：{len(book)} 个局面，{len(book.lines)} 条线路")
    for line in book.lines:
        print("  " + line)
    return 0


def cmd_serve(args) -> int:
    from .server import serve
    return serve(host=args.host, port=args.port, open_browser=not args.no_open)


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caissa", description="Caissa —— 零依赖的国际象棋引擎")
    parser.add_argument("--ascii", action="store_true", help="用 ASCII 棋子而不是 Unicode")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("search", help="分析一个局面，打印逐层结果")
    p.add_argument("--fen", default="")
    p.add_argument("--depth", type=int, default=8)
    p.add_argument("--movetime", type=float, default=0.0)
    p.add_argument("--flip", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("eval", help="打印评估函数的各项分解")
    p.add_argument("--fen", default="")
    p.add_argument("--flip", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("perft", help="跑标准局面的 perft 校验")
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--fen", default="")
    p.add_argument("--divide", action="store_true")
    p.set_defaults(func=cmd_perft)

    p = sub.add_parser("arena", help="跟基线对手下一批棋")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--vs", choices=["random", "material"], default="material")
    p.add_argument("--movetime", type=float, default=0.1)
    p.add_argument("--max-plies", type=int, default=200)
    p.add_argument("--hash", type=float, default=32)
    p.set_defaults(func=cmd_arena)

    p = sub.add_parser("play", help="在终端里对局")
    p.add_argument("--color", default="w", choices=["w", "b", "white", "black"])
    p.add_argument("--level", type=int, default=5, help="引擎搜索层数")
    p.add_argument("--fen", default="")
    p.set_defaults(func=cmd_play)

    p = sub.add_parser("pgn", help="读一份 PGN 并复盘")
    p.add_argument("--in", dest="input", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--encoding", default="utf-8")
    p.set_defaults(func=cmd_pgn)

    p = sub.add_parser("board", help="只打印棋盘")
    p.add_argument("--fen", default="")
    p.add_argument("--flip", action="store_true")
    p.set_defaults(func=cmd_board)

    p = sub.add_parser("book", help="看看内置开局库")
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("uci", help="以 UCI 引擎方式运行（给象棋 GUI 用）")
    p.set_defaults(func=lambda a: __import__("caissa.uci", fromlist=["main"]).main())

    p = sub.add_parser("serve", help="启动网页工作台")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    force_utf8()
    if os.environ.get("CAISSA_ASCII"):
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "ascii", False):
        os.environ["CAISSA_ASCII"] = "1"
    if getattr(args, "version", False):
        from . import __version__
        print(f"caissa {__version__}")
        return 0
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
