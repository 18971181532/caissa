"""代数记谱（SAN）与 PGN。

SAN 的难点不在写，在消歧：两个马都能去同一个格子时，必须写出"哪一个"。
规则是能省则省——先试写列，再试写行，都不行才写全格。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .board import (
    FLAG_CAPTURE, FLAG_CASTLE, START_FEN, Position, move_flags, move_from,
    move_promo, move_to, move_uci, name_of, parse_square,
)

PIECE_LETTER = {2: "N", 3: "B", 4: "R", 5: "Q", 6: "K"}
LETTER_TO_TYPE = {v: k for k, v in PIECE_LETTER.items()}


def to_san(pos: Position, move: int, legal: Optional[Sequence[int]] = None) -> str:
    """生成一步棋的 SAN。pos 不会被改变。"""
    frm = move_from(move)
    to = move_to(move)
    piece = pos.board[frm] & 7
    promo = move_promo(move)
    flags = move_flags(move)
    capture = bool(flags & FLAG_CAPTURE) or bool(pos.board[to])

    if flags & FLAG_CASTLE:
        text = "O-O" if (to & 7) == 6 else "O-O-O"
    elif piece == 1:                       # 兵
        text = ("abcdefgh"[frm & 7] + "x" if capture else "") + name_of(to)
        if promo:
            text += "=" + PIECE_LETTER[promo]
    else:
        text = PIECE_LETTER[piece]
        if legal is None:
            legal = pos.legal_moves()
        # 同名子都能到这个格时，才需要消歧
        rivals = [m for m in legal
                  if m != move and (pos.board[move_from(m)] & 7) == piece
                  and move_to(m) == to]
        if rivals:
            same_file = any((move_from(m) & 7) == (frm & 7) for m in rivals)
            same_rank = any((move_from(m) >> 3) == (frm >> 3) for m in rivals)
            if not same_file:
                text += "abcdefgh"[frm & 7]
            elif not same_rank:
                text += str((frm >> 3) + 1)
            else:
                text += name_of(frm)
        if capture:
            text += "x"
        text += name_of(to)

    # 将军 / 将杀：走一步看一步
    if pos.make(move):
        if pos.in_check():
            text += "#" if not pos.has_legal_move() else "+"
        pos.unmake(move)
    return text


_JUNK = re.compile(r"[+#!?]+$")


def _normalize(text: str) -> str:
    s = text.strip()
    s = s.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    s = s.replace("–", "-").replace("—", "-").replace("×", "x")
    s = s.replace("e.p.", "").replace("ep", "")
    s = _JUNK.sub("", s)
    return s.strip()


def parse_san(pos: Position, text: str) -> Optional[int]:
    """把一段 SAN 解析成着法。"""
    cleaned = _normalize(text)
    if not cleaned:
        return None
    legal = pos.legal_moves()
    for move in legal:
        if to_san(pos, move, legal).rstrip("+#") == cleaned:
            return move

    # 宽松一点：允许省略消歧、允许不写升变符号
    try:
        to = parse_square(cleaned[-2:])
    except ValueError:
        return None
    piece_letter = cleaned[0] if cleaned[0] in LETTER_TO_TYPE else (
        "N" if cleaned.startswith("N") else None)
    promot = None
    if "=" in cleaned:
        promot = LETTER_TO_TYPE.get(cleaned.split("=")[-1][:1])
    candidates = []
    for move in legal:
        if move_to(move) != to:
            continue
        if promot and move_promo(move) != promot:
            continue
        if piece_letter and PIECE_LETTER.get(pos.board[move_from(move)] & 7) != piece_letter:
            continue
        candidates.append(move)
    if len(candidates) == 1:
        return candidates[0]
    return None


@dataclass
class Game:
    """一局棋：起始局面 + 一串 SAN，随时能算出当前局面。"""

    fen: str = START_FEN
    moves: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    result: str = "*"
    _position: Optional[Position] = None

    def __post_init__(self) -> None:
        self._position = Position(self.fen)

    @property
    def position(self) -> Position:
        if self._position is None:
            self._position = Position(self.fen)
        return self._position

    def push(self, move: int) -> str:
        san = to_san(self.position, move)
        if not self.position.make(move):
            raise ValueError(f"不合法着法：{move_uci(move)}")
        self.moves.append(san)
        return san

    def push_san(self, san: str) -> Optional[int]:
        move = parse_san(self.position, san)
        if move is None:
            return None
        self.push(move)
        return move

    def undo(self) -> bool:
        """退一步。做法是重放——比在棋盘上倒着拆安全得多。"""
        if not self.moves:
            return False
        self.moves.pop()
        self._position = Position(self.fen)
        for san in self.moves:
            move = parse_san(self._position, san)
            if move is None or not self._position.make(move):
                break
        return True

    # -- 状态 -------------------------------------------------------------

    def status(self) -> str:
        pos = self.position
        if not pos.has_legal_move():
            return "checkmate" if pos.in_check() else "stalemate"
        if pos.halfmove >= 100 or pos.is_repetition(2) or pos.insufficient_material():
            return "draw"
        return "playing"

    def legal_san(self) -> List[Dict[str, str]]:
        pos = self.position
        legal = pos.legal_moves()
        return [{"uci": move_uci(m), "san": to_san(pos, m, legal)} for m in legal]

    def pgn(self) -> str:
        headers = dict(self.headers)
        headers.setdefault("Result", self.result)
        lines = [f'[{k} "{v}"]' for k, v in headers.items()]
        body = []
        for i in range(0, len(self.moves), 2):
            pair = f"{i // 2 + 1}. {self.moves[i]}"
            if i + 1 < len(self.moves):
                pair += " " + self.moves[i + 1]
            body.append(pair)
        body.append(self.result)
        wrapped: List[str] = []
        line = ""
        for token in body:
            if len(line) + len(token) + 1 > 79:
                wrapped.append(line)
                line = token
            else:
                line = (line + " " + token).strip()
        if line:
            wrapped.append(line)
        return "\n".join(lines) + "\n\n" + "\n".join(wrapped) + "\n"


_COMMENT = re.compile(r"\{[^}]*\}")
_VARIATION = re.compile(r"\([^()]*\)")
_NAG = re.compile(r"\$\d+")
_HEADER = re.compile(r'\[(\w+)\s+"([^"]*)"\]')
_RESULTS = ("1-0", "0-1", "1/2-1/2", "*")


def parse_pgn(text: str) -> Game:
    """读一份（单局）PGN。注释与变例会被丢掉。"""
    headers = {k: v for k, v in _HEADER.findall(text)}
    body = _HEADER.sub("", text)
    body = _COMMENT.sub(" ", body)
    for _ in range(4):                      # 变例可能嵌套
        body = _VARIATION.sub(" ", body)
    body = _NAG.sub(" ", body)

    game = Game(headers.get("FEN", START_FEN), headers=headers)
    for token in body.split():
        if token in _RESULTS:
            continue
        if re.fullmatch(r"\d+\.(\.\.)?", token):
            continue
        if token[0].isdigit() and "." in token:      # "1.e4"
            token = token.split(".", 1)[1]
        if not token:
            continue
        if game.push_san(token) is None:
            break
    result = headers.get("Result", "*")
    game.result = result if result in _RESULTS else game.result
    return game


__all__ = ["to_san", "parse_san", "Game", "parse_pgn"]
