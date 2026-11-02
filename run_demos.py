#!/usr/bin/env python3
"""跑一遍项目里的演示，并把图写到 docs/。

    python run_demos.py              # 全部（对局部分只跑几盘）
    python run_demos.py board perft  # 只跑指定的
    python run_demos.py --full       # 对局跑满 20 盘

图是手写的 SVG：没有绘图库，也就不需要装任何东西。README 直接引用它们。
"""

from __future__ import annotations

import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from caissa.arena import engine_player, match, material_player, random_player
from caissa.board import PIECE_CHARS, Position, move_uci
from caissa.console import force_utf8, ljust, paint, rule
from caissa.eval import evaluate, format_score
from caissa.perft import SUITE, perft
from caissa.san import parse_pgn, to_san
from caissa.search import Engine, Limits
from caissa.service import Coach

DOCS = os.path.join(ROOT, "docs")

# 一张"意大利开局"的中局，棋盘图用这个局面
BOARD_FEN = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/2N2N2/PPPP1PPP/R1BQK2R w KQkq - 4 4"
BOARD_LAST = "g8f6"

# 搜索曲线用一个正常开局，层数够多、分数变化够明显
SEARCH_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"

LIGHT = "#f0d9b5"
DARK = "#b58863"
INK = "#2b2b2b"
PAPER = "#fbfbf8"
ACCENT = "#b23a48"
BLUE = "#3c6e9f"


# --------------------------------------------------------------------------
# SVG 小工具
# --------------------------------------------------------------------------

def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" '
        f'font-family="-apple-system, Segoe UI, Noto Sans SC, Helvetica, Arial, sans-serif">\n'
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>\n'
        f"{body}\n</svg>\n"
    )


def _text(x, y, content, size=13, fill=INK, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{content}</text>')


def _save(name: str, content: str) -> str:
    os.makedirs(DOCS, exist_ok=True)
    path = os.path.join(DOCS, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


# --------------------------------------------------------------------------
# 1. 棋盘图
# --------------------------------------------------------------------------

def board_svg(pos: Position, last: str = "") -> str:
    margin, cell = 30, 56
    size = margin * 2 + cell * 8
    body = [_text(margin, 20, "Caissa · 意大利开局", 13, "#7a6a58")]

    last_squares = ()
    if last:
        # 只取起终点来高亮：这一步是"上一手"，在当前局面里已经不能再走了，
        # 所以不能走 resolve（那是拿当前走子方去校验）。
        raw = _uci(last)
        if raw is not None:
            last_squares = (raw & 63, (raw >> 6) & 63)

    for rank in range(8):
        for file in range(8):
            sq = (7 - rank) * 8 + file
            x = margin + file * cell
            y = margin + rank * cell
            dark = (rank + file) % 2 == 0
            body.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                        f'fill="{DARK if dark else LIGHT}"/>')
            if sq in last_squares:
                body.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                            f'fill="none" stroke="#f2c14e" stroke-width="4"/>')

            piece = pos.board[sq]
            if not piece:
                continue
            letter = PIECE_CHARS[piece]
            white = letter.isupper()
            cx, cy = x + cell / 2, y + cell / 2
            body.append(f'<circle cx="{cx}" cy="{cy}" r="21" '
                        f'fill="{"#fdfdfb" if white else "#2a2a2a"}" '
                        f'stroke="{"#4a4a4a" if white else "#111"}" stroke-width="1.6"/>')
            body.append(_text(cx, cy + 6.5, letter.upper(),
                              17 if white else 17,
                              "#1f1f1f" if white else "#f5f5f5",
                              "middle", "bold"))

    for file in range(8):
        body.append(_text(margin + file * cell + cell / 2, margin + cell * 8 + 18,
                          "abcdefgh"[file], 12, "#7a6a58", "middle"))
    for rank in range(8):
        body.append(_text(margin - 10, margin + rank * cell + cell / 2 + 4,
                          str(8 - rank), 12, "#7a6a58", "middle"))

    side = "白方走" if pos.turn == 0 else "黑方走"
    body.append(_text(margin, size + 14, f"{side} · 上一步 {last or '—'}",
                      12, "#7a6a58"))
    return _svg(size, size + 26, "\n".join(body))


def _uci(text: str):
    from caissa.board import parse_uci
    return parse_uci(text)


def demo_board() -> None:
    print(paint(rule(), "\033[2m"))
    print(paint("棋盘图", "\033[1m"))
    pos = Position(BOARD_FEN)
    print(pos)
    path = _save("board.svg", board_svg(pos, BOARD_LAST))
    print(f"  → {os.path.relpath(path, ROOT)}")


# --------------------------------------------------------------------------
# 2. perft 图
# --------------------------------------------------------------------------

def perft_svg(rows, depth: int) -> str:
    width, row_h, top = 620, 34, 62
    height = top + row_h * len(rows) + 44
    left, bar_max = 132, 420
    biggest = max(n for _, n in rows) or 1
    body = [_text(24, 28, f"perft({depth})：六个标准局面的叶子数", 15, INK, weight="bold"),
            _text(24, 46, "对数刻度；每一条都跟公开参考值逐一核对过", 11, "#8a7a68")]
    for i, (name, nodes) in enumerate(rows):
        y = top + i * row_h
        ratio = math.log10(nodes + 1) / math.log10(biggest + 1)
        w = max(3, bar_max * ratio)
        body.append(_text(left - 12, y + 16, name, 12, INK, "end"))
        body.append(f'<rect x="{left}" y="{y + 5}" width="{w:.1f}" height="17" '
                    f'rx="3" fill="{BLUE}" opacity="{0.55 + 0.4 * ratio:.2f}"/>')
        body.append(_text(left + w + 8, y + 18, f"{nodes:,}", 11, "#5a4a3a"))
    body.append(_text(left, height - 10, "节点数", 10, "#8a7a68"))
    return _svg(width, height, "\n".join(body))


def demo_perft() -> None:
    print()
    print(paint(rule(), "\033[2m"))
    print(paint("perft 校验", "\033[1m"))
    depth = 3
    rows = []
    head = f"{'局面':<12}{'节点':>12}{'耗时':>10}"
    print(head)
    print("-" * len(head))
    for name, (fen, _expected) in SUITE.items():
        t0 = time.perf_counter()
        nodes = perft(Position(fen), depth)
        elapsed = time.perf_counter() - t0
        rows.append((name, nodes))
        print(f"{name:<12}{nodes:>12,}{elapsed:>9.2f}s")
    path = _save("perft.svg", perft_svg(rows, depth))
    print(f"  → {os.path.relpath(path, ROOT)}")


# --------------------------------------------------------------------------
# 3. 搜索曲线
# --------------------------------------------------------------------------

def search_svg(lines) -> str:
    width, height = 680, 320
    left, right, top, bottom = 62, 58, 82, 52
    plot_w = width - left - right
    plot_h = height - top - bottom
    depths = [int(row["depth"]) for row in lines]
    nodes = [int(row["nodes"]) for row in lines]
    scores = [int(row["score"]) for row in lines]
    max_log = math.log10(max(nodes) + 1)
    span = max(240, max(abs(s) for s in scores) * 2)
    lo, hi = -span / 2, span / 2

    body = [_text(24, 28, "迭代加深：层数、节点与分数", 15, INK, weight="bold"),
            _text(24, 46, "意大利开局 · 每层累计节点（对数）与当前评估", 10, "#8a7a68")]

    # 网格与左轴（节点，10 的整数幂）
    ceiling = int(math.ceil(max_log))
    for exp in range(ceiling + 1):
        ratio = exp / ceiling if ceiling else 0
        y = top + plot_h * (1 - ratio)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
                    f'stroke="#e6ded2" stroke-width="1"/>')
        body.append(_text(left - 8, y + 4, f"{10 ** exp:,}", 9, "#9a8a78", "end"))
    body.append(_text(24, top - 10, "节点（对数）", 9, "#9a8a78"))

    # 节点条形
    slot = plot_w / max(1, len(lines))
    bar_w = slot * 0.42
    for i, n in enumerate(nodes):
        h = plot_h * (math.log10(n + 1) / max_log)
        x = left + slot * i + (slot - bar_w) / 2
        body.append(f'<rect x="{x:.1f}" y="{top + plot_h - h:.1f}" width="{bar_w:.1f}" '
                    f'height="{h:.1f}" rx="2" fill="{BLUE}" opacity="0.26"/>')

    # 分数折线（右轴，以 0 为中心）
    points = []
    for i, s in enumerate(scores):
        x = left + slot * i + slot / 2
        y = top + plot_h - plot_h * (s - lo) / (hi - lo)
        points.append((x, y))
    body.append('<polyline fill="none" stroke="%s" stroke-width="2.4" '
                'stroke-linejoin="round" points="%s"/>'
                % (ACCENT, " ".join(f"{x:.1f},{y:.1f}" for x, y in points)))
    for i, (x, y) in enumerate(points):
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="{ACCENT}"/>')
        label_y = y - 10 if y - 10 > top + 8 else y + 17
        body.append(_text(x, label_y, f"{scores[i] / 100:+.2f}", 9, ACCENT, "middle"))
    for i, d in enumerate(depths):
        body.append(_text(left + slot * i + slot / 2, top + plot_h + 18, str(d),
                          10, "#7a6a58", "middle"))
    body.append(_text(left + plot_w / 2, height - 12, "搜索深度", 10, "#8a7a68", "middle"))
    body.append(_text(width - 14, top - 10, f"分数（±{span // 2 / 100:.1f}）", 9, ACCENT, "end"))
    return _svg(width, height, "\n".join(body))


def demo_search() -> None:
    print()
    print(paint(rule(), "\033[2m"))
    print(paint("搜索：意大利开局，逐层加深", "\033[1m"))
    engine = Engine(16.0)
    result = engine.search(Position(SEARCH_FEN), Limits(depth=6))
    head = f"{'层':>3}{'分数':>9}{'节点':>10}  主变"
    print(head)
    print("-" * 68)
    for row in result.lines:
        pv = " ".join(row["pv"][:5])          # type: ignore[index]
        print(f"{row['depth']:>3}{format_score(int(row['score'])):>9}"
              f"{int(row['nodes']):>10,}  {pv}")
    print(f"\n最佳着法 {move_uci(result.best_move)}  "
          f"{result.nodes:,} 节点 / {result.time:.2f}s "
          f"({result.nps:,.0f} nps)")
    path = _save("search.svg", search_svg(result.lines))
    print(f"  → {os.path.relpath(path, ROOT)}")


# --------------------------------------------------------------------------
# 4. 评估分解
# --------------------------------------------------------------------------

def demo_eval() -> None:
    print()
    print(paint(rule(), "\033[2m"))
    print(paint("评估函数分解", "\033[1m"))
    for label, fen in (("初始局面", Position().fen()),
                       ("白多一马", "4k3/8/8/8/8/8/8/3NK3 w - - 0 1"),
                       ("白多一后", "4k3/8/8/8/8/8/8/3QK3 w - - 0 1")):
        detail = {}
        score = evaluate(Position(fen), detail)
        parts = "  ".join(f"{k}={v}" for k, v in detail.items())
        print(f"{ljust(label, 12)}{format_score(score):>7}   {paint(parts, '\033[2m')}")


# --------------------------------------------------------------------------
# 5. PGN 复盘
# --------------------------------------------------------------------------

def demo_pgn() -> None:
    print()
    print(paint(rule(), "\033[2m"))
    print(paint("PGN 复盘", "\033[1m"))
    path = os.path.join(ROOT, "examples", "opera-game.pgn")
    if not os.path.isfile(path):
        print("  没有找到 examples/opera-game.pgn")
        return
    with open(path, encoding="utf-8") as fh:
        game = parse_pgn(fh.read())
    print(f"  {game.headers.get('White', '?')} — {game.headers.get('Black', '?')}")
    print(f"  共 {len(game.moves)} 步，结果 {game.result}")
    print("  " + " ".join(game.moves[:24]) + (" ..." if len(game.moves) > 24 else ""))
    print()
    print(game.position)


# --------------------------------------------------------------------------
# 6. 对局
# --------------------------------------------------------------------------

def demo_arena(games: int = 6) -> None:
    print()
    print(paint(rule(), "\033[2m"))
    print(paint(f"对局：引擎 vs 基线（各 {games} 盘）", "\033[1m"))
    engine = Engine(16.0)
    for name, opponent in (("随机走子", random_player),
                           ("只吃子", material_player)):
        t0 = time.perf_counter()
        result = match(engine_player(engine, movetime=0.05), opponent,
                       games=games, max_plies=120)
        elapsed = time.perf_counter() - t0
        elo = result["elo"]
        if math.isinf(elo):
            elo_text = "  全胜" if elo > 0 else "  全负"
        else:
            elo_text = f"{elo:+6.0f}"
        print(f"  vs {ljust(name, 8)} "
              f"{result['wins']}胜 {result['draws']}和 {result['losses']}负  "
              f"得分率 {result['score'] * 100:5.1f}%  "
              f"Elo {elo_text}  ({elapsed:.1f}s)")


# --------------------------------------------------------------------------

DEMOS = {
    "board": demo_board,
    "perft": demo_perft,
    "search": demo_search,
    "eval": demo_eval,
    "pgn": demo_pgn,
    "arena": demo_arena,
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    force_utf8()
    full = "--full" in argv
    argv = [a for a in argv if not a.startswith("-")]
    names = argv or list(DEMOS)
    unknown = [n for n in names if n not in DEMOS]
    if unknown:
        print("未知的演示：" + ", ".join(unknown))
        print("可选：" + ", ".join(DEMOS))
        return 2

    print(paint("Caissa · 演示", "\033[1m"))
    print(paint("零依赖的国际象棋引擎 —— 走子、评估、搜索、对局、网页工作台", "\033[2m"))
    for name in names:
        if name == "arena":
            demo_arena(20 if full else 6)
        else:
            DEMOS[name]()
    print()
    print(paint("完成。图已写入 docs/。", "\033[2m"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
