/* Caissa 工作台。没有框架、没有构建，一个文件说完。 */

const START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const GLYPH = {
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
  P: "♙", N: "♘", B: "♗", R: "♖", Q: "♕", K: "♔",
};
const FILES = "abcdefgh";

const $ = (id) => document.getElementById(id);

const state = {
  baseFen: START,
  plies: [],          // { san, uci, fen }
  view: 0,            // 0 = 初始局面，n = 走了 n 步
  flipped: false,
  human: "w",
  depth: 5,
  movetime: 0.4,
  legal: [],
  selected: null,
  last: null,         // { from, to }
  check: false,
  status: "playing",
  busy: false,
};

/* ---------------------------------------------------------------- 工具 */

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data = {};
  try { data = await res.json(); } catch (e) { /* 空响应 */ }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function currentFen() {
  return state.view === 0 ? state.baseFen : state.plies[state.view - 1].fen;
}

function squareName(sq) {
  return FILES[sq & 7] + String((sq >> 3) + 1);
}

function parseFen(fen) {
  const parts = fen.split(" ");
  const board = new Array(64).fill("");
  let rank = 7, file = 0;
  for (const ch of parts[0]) {
    if (ch === "/") { rank--; file = 0; continue; }
    if (/\d/.test(ch)) { file += Number(ch); continue; }
    board[rank * 8 + file] = ch;
    file++;
  }
  return { board, turn: parts[1] === "b" ? "b" : "w" };
}

function kingSquare(board, color) {
  const want = color === "w" ? "K" : "k";
  for (let i = 0; i < 64; i++) if (board[i] === want) return i;
  return -1;
}

function scoreLabel(score) {
  const MATE = 32000;
  if (Math.abs(score) > MATE - 200) {
    const n = Math.ceil((MATE - Math.abs(score)) / 2);
    return (score < 0 ? "−#" : "#") + n;
  }
  return (score / 100).toFixed(2);
}

/* ---------------------------------------------------------------- 棋盘 */

function renderBoard() {
  const board = $("board");
  const parsed = parseFen(currentFen());
  const pieces = parsed.board;
  board.innerHTML = "";

  const ranks = state.flipped ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
  const files = state.flipped ? [7, 6, 5, 4, 3, 2, 1, 0] : [0, 1, 2, 3, 4, 5, 6, 7];
  const checkSq = state.check ? kingSquare(pieces, parsed.turn) : -1;

  const targets = new Map();
  if (state.selected !== null) {
    for (const move of state.legal) {
      if (move.uci.slice(0, 2) === squareName(state.selected)) {
        const to = move.uci.slice(2, 4);
        targets.set(to, Boolean(move.san.includes("x")));
      }
    }
  }

  for (let i = 0; i < 64; i++) {
    const rank = ranks[Math.floor(i / 8)];
    const file = files[i % 8];
    const sq = (rank - 1) * 8 + file;
    const el = document.createElement("div");
    el.className = "sq " + (((rank - 1) + file) % 2 === 0 ? "dark" : "light");
    el.dataset.sq = String(sq);

    if (state.last && (state.last.from === sq || state.last.to === sq)) el.classList.add("last");
    if (state.selected === sq) el.classList.add("sel");
    if (checkSq === sq) el.classList.add("check");

    const piece = pieces[sq];
    if (piece) {
      const span = document.createElement("span");
      span.className = "piece " + (piece === piece.toUpperCase() ? "w" : "b");
      span.textContent = GLYPH[piece] || "";
      el.appendChild(span);
    }

    const name = squareName(sq);
    if (targets.has(name)) {
      const dot = document.createElement("div");
      dot.className = targets.get(name) ? "hint-ring" : "hint-dot";
      el.appendChild(dot);
    }

    // 边上标坐标：左边一列写横行号，最下一行写列号
    if (i % 8 === 0) {
      const c = document.createElement("span");
      c.className = "coord rank";
      c.textContent = String(rank);
      el.appendChild(c);
    }
    if (Math.floor(i / 8) === 7) {
      const c = document.createElement("span");
      c.className = "coord file";
      c.textContent = FILES[file];
      el.appendChild(c);
    }

    board.appendChild(el);
  }
}

/* ---------------------------------------------------------------- 面板 */

function renderStatus(data) {
  const parsed = parseFen(currentFen());
  const turn = parsed.turn;
  $("turn-dot").className = "dot" + (turn === "b" ? " black" : "");
  $("turn-text").textContent = turn === "w" ? "白方走棋" : "黑方走棋";

  const pill = $("status-pill");
  pill.textContent = (data && data.status_text) || "进行中";
  pill.classList.toggle("over", Boolean(data && data.status && data.status !== "playing"));

  let sub = "";
  if (data && data.status === "checkmate") {
    sub = turn === "w" ? "白方被将杀 —— 黑方胜" : "黑方被将杀 —— 白方胜";
  } else if (data && data.status === "stalemate") {
    sub = "无子可动，逼和";
  } else if (data && data.status === "draw") {
    sub = "五十回合 / 三次重复 / 子力不足";
  } else if (data && data.check) {
    sub = "被将军，必须应将";
  } else if (state.busy) {
    sub = "引擎正在思考…";
  } else if (state.view !== state.plies.length) {
    sub = "正在回顾历史局面，走子会截断后面的棋谱";
  } else {
    sub = "点击棋子，再点目标格";
  }
  $("status-sub").textContent = sub;
}

function renderEval(data) {
  if (!data || typeof data.eval !== "number") return;
  const parsed = parseFen(currentFen());
  // evalbar 永远是白方视角
  const white = parsed.turn === "w" ? data.eval : -data.eval;
  const clamped = Math.max(-900, Math.min(900, white));
  const pct = 50 + 50 * Math.tanh(clamped / 380);
  $("evalfill").style.height = pct.toFixed(1) + "%";
  $("evallabel").textContent = scoreLabel(white);
}

function renderMoves() {
  const box = $("moves");
  box.innerHTML = "";
  const total = state.plies.length;
  $("ply-count").textContent = total ? `${total} 半步` : "空";
  const rows = Math.max(1, Math.ceil(total / 2));
  for (let r = 0; r < rows; r++) {
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = String(r + 1) + ".";
    box.appendChild(no);

    for (let k = 0; k < 2; k++) {
      const index = r * 2 + k;              // 0-based ply
      const cell = document.createElement("span");
      cell.className = "mv";
      if (index < total) {
        cell.textContent = state.plies[index].san;
        if (index + 1 === state.view) cell.classList.add("current");
        cell.onclick = () => {
          state.view = index + 1;
          state.selected = null;
          refreshFromHistory();
        };
      } else {
        cell.classList.add("empty");
      }
      box.appendChild(cell);
    }
  }
}

function renderLines(data) {
  const box = $("lines");
  box.innerHTML = "";
  if (!data || !data.lines || !data.lines.length) {
    box.innerHTML = '<div class="line-row"><span class="pv">还没有搜索结果</span></div>';
    $("search-summary").textContent = "—";
    return;
  }
  const rows = data.lines.slice(-6).reverse();
  for (let i = 0; i < rows.length; i++) {
    const line = rows[i];
    const row = document.createElement("div");
    row.className = "line-row" + (i === 0 ? " best" : "");
    row.innerHTML =
      `<span class="d">${line.depth}</span>` +
      `<span class="s">${line.score_text}</span>` +
      `<span class="n">${fmtNodes(line.nodes)}</span>` +
      `<span class="pv">${line.pv.slice(0, 8).join(" ") || "…"}</span>`;
    box.appendChild(row);
  }
  const best = data.lines[data.lines.length - 1];
  $("search-summary").textContent =
    `${data.depth} 层 · ${fmtNodes(data.nodes)} 节点 · ${fmtNps(data.nps)}`;
}

function fmtNodes(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}
function fmtNps(n) {
  if (!n) return "0";
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M/s";
  if (n >= 1000) return Math.round(n / 1000) + "k/s";
  return Math.round(n) + "/s";
}

function banner(text) {
  const el = $("banner");
  if (!text) { el.hidden = true; return; }
  el.querySelector("span").textContent = text;
  el.hidden = false;
}

/* ---------------------------------------------------------------- 流程 */

function applyServerState(data) {
  state.legal = data.legal || [];
  state.check = Boolean(data.check);
  state.status = data.status || "playing";
  $("fen").value = data.fen;
}

async function loadState(fen) {
  const data = await post("/api/state", { fen });
  applyServerState(data);
  return data;
}

async function refreshFromHistory() {
  const data = await loadState(currentFen());
  state.last = null;
  renderBoard();
  renderMoves();
  renderStatus(data);
  renderEval(data);
  const over = data.status !== "playing";
  banner(over ? (data.status === "checkmate" ? "将杀" : data.status === "stalemate" ? "逼和" : "和棋") : "");
}

function pushMove(san, uci, fen) {
  if (state.view < state.plies.length) state.plies = state.plies.slice(0, state.view);
  state.plies.push({ san, uci, fen });
  state.view = state.plies.length;
  state.last = { from: uci.slice(0, 2), to: uci.slice(2, 4) };
}

function turnOf(fen) {
  return fen.split(" ")[1] === "b" ? "b" : "w";
}

function engineToMove() {
  if (state.human === "none") return state.status === "playing";
  return turnOf(currentFen()) !== state.human && state.status === "playing";
}

async function engineMove() {
  if (state.busy) return;
  if (!engineToMove()) return;
  state.busy = true;
  renderStatus(null);
  const fen = currentFen();
  try {
    const analysis = await post("/api/engine", {
      fen,
      depth: state.depth,
      movetime: state.movetime,
      book: true,
    });
    renderLines(analysis);
    if (!analysis.best) { state.busy = false; return; }
    const applied = await post("/api/move", { fen, move: analysis.best });
    pushMove(applied.san, applied.uci, applied.fen);
    applyServerState(applied);
    renderBoard();
    renderMoves();
    renderStatus(applied);
    renderEval({ eval: analysis.score, fen: fen });
    if (applied.status !== "playing") {
      banner(applied.status === "checkmate" ? "将杀"
        : applied.status === "stalemate" ? "逼和" : "和棋");
    }
  } catch (err) {
    $("status-sub").textContent = "引擎出错：" + err.message;
  } finally {
    state.busy = false;
  }
  if (engineToMove()) setTimeout(engineMove, 260);
  else renderStatus(await loadState(currentFen()));
}

async function playHuman(uci) {
  const fen = currentFen();
  try {
    const data = await post("/api/move", { fen, move: uci });
    pushMove(data.san, data.uci, data.fen);
    applyServerState(data);
    state.selected = null;
    renderBoard();
    renderMoves();
    renderStatus(data);
    renderEval(data);
    if (data.status !== "playing") {
      banner(data.status === "checkmate" ? "将杀"
        : data.status === "stalemate" ? "逼和" : "和棋");
      return;
    }
    setTimeout(engineMove, 120);
  } catch (err) {
    $("status-sub").textContent = "走不了：" + err.message;
  }
}

/* ---------------------------------------------------------------- 事件 */

$("board").addEventListener("click", (event) => {
  const cell = event.target.closest(".sq");
  if (!cell) return;
  const sq = Number(cell.dataset.sq);
  const parsed = parseFen(currentFen());
  const piece = parsed.board[sq];
  const mine = parsed.turn === state.human || state.human === "none";
  const name = squareName(sq);

  if (state.selected !== null) {
    const chosen = state.legal.find(
      (m) => m.uci.slice(0, 2) === squareName(state.selected) && m.uci.slice(2, 4) === name);
    if (chosen) {
      if (state.busy) return;
      playHuman(chosen.uci);
      return;
    }
  }
  if (piece && mine && (piece === piece.toUpperCase() ? "w" : "b") === parsed.turn) {
    state.selected = sq;
    renderBoard();
    return;
  }
  state.selected = null;
  renderBoard();
});

$("btn-new").onclick = async () => {
  state.plies = [];
  state.view = 0;
  state.baseFen = START;
  state.selected = null;
  state.last = null;
  const data = await loadState(START);
  renderBoard(); renderMoves(); renderStatus(data); renderEval(data);
  banner("");
  if (engineToMove()) engineMove();
};

$("btn-undo").onclick = async () => {
  if (!state.plies.length) return;
  state.busy = false;
  let drop = 1;
  if (state.human !== "none" && state.plies.length >= 2) drop = 2;
  if (state.human === "none") drop = 1;
  if (turnOf(currentFen()) !== state.human && state.plies.length >= 2) drop = 2;
  state.plies = state.plies.slice(0, Math.max(0, state.plies.length - drop));
  state.view = state.plies.length;
  state.last = null;
  banner("");
  const data = await loadState(currentFen());
  renderBoard(); renderMoves(); renderStatus(data); renderEval(data);
};

$("btn-flip").onclick = () => { state.flipped = !state.flipped; renderBoard(); };

$("btn-analyze").onclick = async () => {
  if (state.busy) return;
  state.busy = true;
  renderStatus(null);
  try {
    const analysis = await post("/api/engine", {
      fen: currentFen(), depth: state.depth, movetime: state.movetime, book: false,
    });
    renderLines(analysis);
    $("status-sub").textContent =
      `建议 ${analysis.best_san}（${analysis.score_text}），${analysis.depth} 层`;
    renderEval({ eval: analysis.score });
  } catch (err) {
    $("status-sub").textContent = "分析失败：" + err.message;
  } finally {
    state.busy = false;
    renderStatus(await loadState(currentFen()));
  }
};

$("side").onchange = () => {
  state.human = $("side").value;
  if (engineToMove()) engineMove();
};
function readLevel() {
  const option = $("level").selectedOptions[0];
  state.depth = Number(option.value);
  state.movetime = Number(option.dataset.time || 0);
}
$("level").onchange = readLevel;

$("btn-load").onclick = async () => {
  const fen = $("fen").value.trim();
  if (!fen) return;
  try {
    state.baseFen = fen;
    state.plies = [];
    state.view = 0;
    state.selected = null;
    state.last = null;
    banner("");
    const data = await loadState(fen);
    renderBoard(); renderMoves(); renderStatus(data); renderEval(data);
    if (engineToMove()) engineMove();
  } catch (err) {
    $("status-sub").textContent = "FEN 有问题：" + err.message;
  }
};

$("fen").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-load").click();
});

/* ---------------------------------------------------------------- 启动 */

(async function boot() {
  try {
    const health = await fetch("/api/health").then((r) => r.json());
    $("ver").textContent = "v" + health.version;
  } catch (e) { /* 忽略 */ }
  const data = await loadState(START);
  renderBoard(); renderMoves(); renderStatus(data); renderEval(data);
  readLevel();
  // 默认让引擎先走一步（如果用户执黑）
  if (engineToMove()) engineMove();
})();
