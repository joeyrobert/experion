import { Chess } from './vendor/chess.js';
import { Board } from './board.js';
import { Engine } from './engine.js';

const $ = (id) => document.getElementById(id);

const LEVELS = {
  beginner: { depth: 1 },
  casual: { depth: 4 },
  club: { movetime: 300 },
  strong: { movetime: 2000 },
  maximum: { movetime: 8000 },
};

const game = new Chess();
let startFen = null; // null = standard start position
let humanSide = 'w'; // 'w' | 'b'
let auto = false;
let thinking = false;
let searchToken = 0;
let lastEval = null; // {cpWhite, mate}
let engine;
let engineError = null;

const board = new Board($('board'), {
  targetsFor: (sq) => (canHumanMove() ? game.moves({ square: sq, verbose: true }).map((m) => m.to) : []),
  onMove: (from, to) => humanMove(from, to),
});

function canHumanMove() {
  return !thinking && !auto && !game.isGameOver() && game.turn() === humanSide && !engineError;
}

function uciHistory() {
  return game.history({ verbose: true }).map((m) => m.from + m.to + (m.promotion || ''));
}

function kingSquare(color) {
  for (const row of game.board()) for (const p of row) if (p && p.type === 'k' && p.color === color) return p.square;
  return null;
}

function render() {
  board.setPosition(game.board());
  const hist = game.history({ verbose: true });
  const last = hist[hist.length - 1];
  board.lastMove = last ? { from: last.from, to: last.to } : null;
  board.checkSquare = game.inCheck() ? kingSquare(game.turn()) : null;
  board.setLocked(!canHumanMove());
  board.render();
  renderMoves(hist);
  renderStatus();
  renderEval();
}

function renderMoves(hist) {
  const el = $('moves');
  el.innerHTML = '';
  hist.forEach((m, i) => {
    if (i % 2 === 0) {
      const n = document.createElement('span');
      n.className = 'num';
      n.textContent = i / 2 + 1 + '.';
      el.appendChild(n);
    }
    const s = document.createElement('span');
    s.className = 'mv' + (i === hist.length - 1 ? ' current' : '');
    s.textContent = m.san;
    el.appendChild(s);
  });
  el.scrollTop = el.scrollHeight;
}

function renderStatus() {
  const s = $('status');
  s.className = '';
  if (engineError) { s.textContent = engineError; s.className = 'error'; return; }
  if (game.isCheckmate()) {
    s.textContent = 'Checkmate. ' + (game.turn() === 'w' ? 'Black' : 'White') + ' wins.';
    s.className = 'over';
  } else if (game.isStalemate()) { s.textContent = 'Draw by stalemate.'; s.className = 'over'; }
  else if (game.isThreefoldRepetition()) { s.textContent = 'Draw by repetition.'; s.className = 'over'; }
  else if (game.isInsufficientMaterial()) { s.textContent = 'Draw: insufficient material.'; s.className = 'over'; }
  else if (game.isDraw()) { s.textContent = 'Draw by the fifty-move rule.'; s.className = 'over'; }
  else if (thinking) { s.textContent = 'Experion is thinking…'; s.className = 'thinking'; }
  else if (auto) s.textContent = 'Engine vs. engine';
  else s.textContent = game.turn() === humanSide ? 'Your move' + (game.inCheck() ? ' (check)' : '') : 'Waiting for the engine…';
}

function renderEval() {
  const fill = $('eval-fill');
  const label = $('eval-label');
  if (!lastEval) { fill.style.height = '50%'; label.textContent = ''; return; }
  const cp = lastEval.mate !== null ? Math.sign(lastEval.mate) * 100000 : lastEval.cpWhite;
  fill.style.height = 100 / (1 + Math.exp(-cp / 400)) + '%';
  label.textContent = lastEval.mate !== null
    ? (lastEval.mate > 0 ? '#' : '-#') + Math.abs(lastEval.mate)
    : (cp > 0 ? '+' : '') + (cp / 100).toFixed(2);
}

function pvToSan(pv) {
  const tmp = new Chess(game.fen());
  const out = [];
  for (const u of pv.slice(0, 8)) {
    try {
      const m = tmp.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] });
      out.push(m.san);
    } catch { break; }
  }
  return out;
}

function showInfo(info, sideToMove) {
  if (info.depth === undefined) return;
  if (info.scoreType === 'cp') lastEval = { cpWhite: sideToMove === 'w' ? info.score : -info.score, mate: null };
  else if (info.scoreType === 'mate') lastEval = { cpWhite: 0, mate: sideToMove === 'w' ? info.score : -info.score };
  const nps = info.nps ? (info.nps / 1e6).toFixed(2) + ' Mn/s' : '';
  $('info').textContent = `depth ${info.depth}` + (nps ? ` · ${nps}` : '') + (info.pv.length ? ` · ${pvToSan(info.pv).join(' ')}` : '');
  renderEval();
}

async function engineMove() {
  if (game.isGameOver() || thinking) return;
  thinking = true;
  const token = ++searchToken;
  const side = game.turn();
  render();
  try {
    const uci = await engine.search(
      { startFen, moves: uciHistory(), limit: LEVELS[$('level').value] },
      (info) => { if (token === searchToken) showInfo(info, side); },
    );
    if (token !== searchToken) return;
    thinking = false;
    if (uci) game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    render();
    afterMove();
  } catch (err) {
    if (token !== searchToken) return; // cancelled by undo/new game
    thinking = false;
    engineError = 'The engine could not start: ' + err.message + '. Open this page over http(s), not from a file.';
    render();
  }
}

function afterMove() {
  if (game.isGameOver()) { auto = false; syncAutoButton(); render(); return; }
  if (auto || game.turn() !== humanSide) setTimeout(engineMove, auto ? 250 : 120);
}

function choosePromotion(color) {
  return new Promise((resolve) => {
    const box = $('promotion');
    box.innerHTML = '';
    for (const t of ['q', 'r', 'b', 'n']) {
      const b = document.createElement('button');
      b.className = 'piece ' + (color === 'w' ? 'white' : 'black');
      b.textContent = { q: '♛', r: '♜', b: '♝', n: '♞' }[t] + '︎';
      b.setAttribute('aria-label', { q: 'Queen', r: 'Rook', b: 'Bishop', n: 'Knight' }[t]);
      b.onclick = () => { box.hidden = true; resolve(t); };
      box.appendChild(b);
    }
    box.hidden = false;
  });
}

async function humanMove(from, to) {
  if (!canHumanMove()) return;
  const piece = game.get(from);
  let promotion;
  if (piece && piece.type === 'p' && (to[1] === '8' || to[1] === '1')) promotion = await choosePromotion(piece.color);
  try {
    game.move({ from, to, promotion });
  } catch { render(); return; }
  render();
  afterMove();
}

function cancelSearch() {
  searchToken++;
  if (thinking) { thinking = false; engine.cancel(); }
}

function newGame(fen) {
  cancelSearch();
  auto = false;
  syncAutoButton();
  lastEval = null;
  $('info').textContent = '';
  game.reset();
  startFen = null;
  if (fen) { game.load(fen); startFen = game.fen(); }
  humanSide = $('side').value === 'b' ? 'b' : 'w';
  board.setOrientation(humanSide);
  render();
  afterMove();
}

function undo() {
  cancelSearch();
  auto = false;
  syncAutoButton();
  if (game.history().length === 0) { render(); return; }
  game.undo();
  if (game.turn() !== humanSide && game.history().length) game.undo();
  lastEval = null;
  $('info').textContent = '';
  render();
}

function syncAutoButton() {
  $('auto').classList.toggle('active', auto);
  $('auto').textContent = auto ? 'Stop engine vs. engine' : 'Engine vs. engine';
}

$('new').onclick = () => newGame();
$('flip').onclick = () => board.flip();
$('undo').onclick = undo;
$('go').onclick = () => { if (!thinking) { auto = false; syncAutoButton(); engineMove(); } };
$('auto').onclick = () => {
  auto = !auto;
  syncAutoButton();
  if (auto) engineMove();
  else { cancelSearch(); render(); }
};
$('side').onchange = () => newGame();
$('copy-fen').onclick = () => copy(game.fen(), $('copy-fen'));
$('copy-pgn').onclick = () => copy(game.pgn(), $('copy-pgn'));
$('load-fen').onclick = () => {
  const fen = prompt('Paste a FEN to play from:');
  if (!fen) return;
  try { new Chess(fen.trim()); } catch { alert('That FEN is not valid.'); return; }
  newGame(fen.trim());
};

async function copy(text, button) {
  try { await navigator.clipboard.writeText(text); } catch { return; }
  const old = button.textContent;
  button.textContent = 'Copied';
  setTimeout(() => { button.textContent = old; }, 1200);
}

try {
  engine = new Engine();
} catch (e) {
  engineError = 'This browser cannot run the engine (needs module workers and WebAssembly).';
}
newGame();
