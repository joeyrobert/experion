import { Chess } from './vendor/chess.js';
import { Board } from './board.js';
import { ENGINES, createEngine } from './engines.js';
import { loadOpenings } from './openings.js';

const $ = (id) => document.getElementById(id);

const LEVELS = {
  beginner: { depth: 1 },
  casual: { depth: 4 },
  club: { movetime: 300 },
  strong: { movetime: 2000 },
  maximum: { movetime: 8000 },
};

const registry = new Map(ENGINES.map((e) => [e.id, e]));
const instances = new Map(); // engine id -> adapter (created on first use)
const openings = loadOpenings(Chess);

const game = new Chess();
let startFen = null; // null = standard start position
const players = { w: 'human', b: 'experion' }; // 'human' or an engine id
let paused = false;
let thinking = false;
let thinkingId = null;
let searchToken = 0;
let lastEval = null; // {cpWhite, mate}
let engineError = null;
let currentLine = null;
let bridgeUrl = null;

const board = new Board($('board'), {
  targetsFor: (sq) => (canHumanMove() ? game.moves({ square: sq, verbose: true }).map((m) => m.to) : []),
  onMove: (from, to) => humanMove(from, to),
});

const nameOf = (id) => (id === 'human' ? null : registry.get(id).name);
const humanCount = () => (players.w === 'human') + (players.b === 'human');

function playerLabel(color) {
  const id = players[color];
  if (id !== 'human') return nameOf(id);
  return humanCount() === 2 ? (color === 'w' ? 'White' : 'Black') : 'You';
}

function canHumanMove() {
  return !thinking && !game.isGameOver() && players[game.turn()] === 'human' && !engineError;
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
  renderTags();
  renderControls();
}

function renderTags() {
  const top = board.orientation === 'w' ? 'b' : 'w';
  const bottom = board.orientation;
  for (const [el, color] of [[$('tag-top'), top], [$('tag-bottom'), bottom]]) {
    el.textContent = (color === 'w' ? '○ ' : '● ') + playerLabel(color);
    el.classList.toggle('active', !game.isGameOver() && game.turn() === color);
  }
}

function renderControls() {
  const anyEngine = players.w !== 'human' || players.b !== 'human';
  $('pause').disabled = !anyEngine;
  $('pause').textContent = paused ? (game.history().length ? 'Resume' : 'Start') : 'Pause';
  $('pause').classList.toggle('active', paused);
  $('go').disabled = thinking;
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
  const side = game.turn();
  const who = playerLabel(side);
  if (engineError) { s.textContent = engineError; s.className = 'error'; return; }
  if (game.isCheckmate()) {
    s.textContent = 'Checkmate. ' + playerLabel(side === 'w' ? 'b' : 'w') + ' wins.';
    s.className = 'over';
  } else if (game.isStalemate()) { s.textContent = 'Draw by stalemate.'; s.className = 'over'; }
  else if (game.isThreefoldRepetition()) { s.textContent = 'Draw by repetition.'; s.className = 'over'; }
  else if (game.isInsufficientMaterial()) { s.textContent = 'Draw: insufficient material.'; s.className = 'over'; }
  else if (game.isDraw()) { s.textContent = 'Draw by the fifty-move rule.'; s.className = 'over'; }
  else if (thinking) { s.textContent = nameOf(thinkingId) + ' is thinking…'; s.className = 'thinking'; }
  else if (paused && players[side] !== 'human') s.textContent = game.history().length ? 'Paused. Press Resume to continue.' : 'Ready. Press Start to begin.';
  else if (players[side] === 'human') s.textContent = (humanCount() === 2 ? who + ' to move' : 'Your move') + (game.inCheck() ? ' (check)' : '');
  else s.textContent = who + ' to move';
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
      out.push(tmp.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }).san);
    } catch { break; }
  }
  return out;
}

function showInfo(info, sideToMove, name) {
  if (info.depth === undefined) return;
  if (info.scoreType === 'cp') lastEval = { cpWhite: sideToMove === 'w' ? info.score : -info.score, mate: null };
  else if (info.scoreType === 'mate') lastEval = { cpWhite: 0, mate: sideToMove === 'w' ? info.score : -info.score };
  const nps = info.nps ? (info.nps / 1e6).toFixed(2) + ' Mn/s' : '';
  $('info').textContent = `${name}: depth ${info.depth}` + (nps ? ` · ${nps}` : '') + (info.pv.length ? ` · ${pvToSan(info.pv).join(' ')}` : '');
  renderEval();
}

function instanceFor(id) {
  if (!instances.has(id)) instances.set(id, createEngine(registry.get(id), { bridgeUrl }));
  return instances.get(id);
}

// A move from a known opening line, if "random lines" is on and the game still follows one.
function bookMove() {
  if ($('openings').value !== 'lines') return null;
  const hist = uciHistory();
  const follows = (line) => line.length > hist.length && hist.every((m, i) => m === line[i]);
  if (!currentLine || !follows(currentLine)) {
    const candidates = openings.filter(follows);
    if (!candidates.length) return null;
    currentLine = candidates[Math.floor(Math.random() * candidates.length)];
  }
  return currentLine[hist.length];
}

function playUci(uci) {
  try {
    game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    return true;
  } catch { return false; }
}

async function engineMove(forceId) {
  if (game.isGameOver() || thinking) return;
  const side = game.turn();
  const id = forceId || players[side];
  if (!id || id === 'human') return;
  const book = bookMove();
  if (book && playUci(book)) {
    $('info').textContent = 'Opening line';
    render();
    afterMove();
    return;
  }
  thinking = true;
  thinkingId = id;
  const token = ++searchToken;
  $('info').textContent = nameOf(id) + ': thinking…';
  render();
  try {
    const uci = await instanceFor(id).search(
      { startFen, moves: uciHistory(), limit: LEVELS[$('level').value] },
      (info) => { if (token === searchToken) showInfo(info, side, nameOf(id)); },
    );
    if (token !== searchToken) return;
    thinking = false;
    if (!uci || !playUci(uci)) {
      if (uci) engineError = `${nameOf(id)} returned a move (${uci}) that is not legal here.`;
    }
    render();
    afterMove();
  } catch (err) {
    if (token !== searchToken) return; // cancelled by undo, new game or a player change
    thinking = false;
    engineError = `${nameOf(id)} could not run: ${err.message}.` + (id.startsWith('bridge:') ? '' : ' Open this page over http(s), not from a file.');
    render();
  }
}

function afterMove() {
  if (game.isGameOver() || engineError) { render(); return; }
  if (paused || thinking) return;
  if (players[game.turn()] !== 'human') setTimeout(() => { if (!paused && !thinking) engineMove(); }, humanCount() === 0 ? 300 : 120);
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
  try { game.move({ from, to, promotion }); } catch { render(); return; }
  paused = false;
  render();
  afterMove();
}

function cancelSearch() {
  searchToken++;
  if (thinking) {
    thinking = false;
    const inst = instances.get(thinkingId);
    if (inst) inst.cancel();
  }
}

function readPlayers() {
  players.w = $('white').value;
  players.b = $('black').value;
}

function chooseOrientation() {
  if (players.w === 'human') board.setOrientation('w');
  else if (players.b === 'human') board.setOrientation('b');
  else board.setOrientation('w');
}

function newGame(fen) {
  cancelSearch();
  paused = false;
  engineError = null;
  lastEval = null;
  currentLine = null;
  $('info').textContent = '';
  game.reset();
  startFen = null;
  if (fen) { game.load(fen); startFen = game.fen(); }
  readPlayers();
  chooseOrientation();
  render();
  afterMove();
}

// Changing who plays only changes the setup. It never starts a search: if an engine is now to
// move, the game waits until the user resumes, plays a move or starts a new game.
function playersChanged() {
  cancelSearch();
  engineError = null;
  readPlayers();
  chooseOrientation();
  if (!game.isGameOver() && players[game.turn()] !== 'human') paused = true;
  render();
}

function undo() {
  cancelSearch();
  if (game.history().length === 0) { render(); return; }
  game.undo();
  if (humanCount() === 1 && players[game.turn()] !== 'human' && game.history().length) game.undo();
  else if (humanCount() === 0) paused = true;
  lastEval = null;
  currentLine = null;
  $('info').textContent = '';
  render();
}

$('new').onclick = () => newGame();
$('flip').onclick = () => { board.flip(); renderTags(); };
$('undo').onclick = undo;
$('white').onchange = playersChanged;
$('black').onchange = playersChanged;
$('pause').onclick = () => {
  paused = !paused;
  if (paused) { cancelSearch(); }
  render();
  if (!paused) afterMove();
};
$('go').onclick = () => {
  if (thinking || game.isGameOver()) return;
  // Ask an engine to play the side to move: the side's own engine, else the opponent's, else Experion.
  const side = game.turn();
  const id = players[side] !== 'human' ? players[side] : (players[side === 'w' ? 'b' : 'w'] !== 'human' ? players[side === 'w' ? 'b' : 'w'] : 'experion');
  engineMove(id);
};
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

// ---- local engine bridge (tools/engine-bridge.mjs) ------------------------------------------

function addEngineOptions(list) {
  for (const def of list) {
    registry.set(def.id, def);
    for (const sel of [$('white'), $('black')]) {
      if ([...sel.options].some((o) => o.value === def.id)) continue;
      const o = document.createElement('option');
      o.value = def.id;
      o.textContent = def.name;
      sel.appendChild(o);
    }
  }
}

async function connectBridge(url) {
  const res = await fetch(url.replace(/\/$/, '') + '/engines');
  if (!res.ok) throw new Error('bridge returned ' + res.status);
  const list = await res.json();
  bridgeUrl = url.replace(/\/$/, '');
  addEngineOptions(list.map((e) => ({ id: 'bridge:' + e.id, remoteId: e.id, name: e.name + ' (local)', kind: 'bridge' })));
  return list.length;
}

$('bridge').onclick = async () => {
  const url = prompt('Local engine bridge URL (run "node tools/engine-bridge.mjs" on this computer):', bridgeUrl || 'http://127.0.0.1:8787');
  if (!url) return;
  try {
    const n = await connectBridge(url);
    $('bridge').textContent = `Local engines (${n})`;
    try { localStorage.setItem('experion.bridge', url); } catch { /* storage unavailable */ }
  } catch (err) {
    alert('Could not reach a bridge at ' + url + '.\n' + err.message);
  }
};

// ---- start-up ---------------------------------------------------------------------------------

function fillPlayerSelects() {
  for (const sel of [$('white'), $('black')]) {
    sel.innerHTML = '';
    const human = document.createElement('option');
    human.value = 'human';
    human.textContent = 'Human';
    sel.appendChild(human);
  }
  addEngineOptions(ENGINES);
}

fillPlayerSelects();
const query = new URLSearchParams(location.search);
const pick = (sel, wanted, fallback) => { sel.value = registry.has(wanted) || wanted === 'human' ? wanted : fallback; };
pick($('white'), query.get('white') || 'human', 'human');
pick($('black'), query.get('black') || 'experion', 'experion');
if (query.get('level') && LEVELS[query.get('level')]) $('level').value = query.get('level');
if (query.get('openings') === 'none') $('openings').value = 'none';

if (query.has('bridge')) {
  let url = query.get('bridge');
  try { url = url || localStorage.getItem('experion.bridge'); } catch { /* storage unavailable */ }
  connectBridge(url || 'http://127.0.0.1:8787').then((n) => { $('bridge').textContent = `Local engines (${n})`; }).catch(() => {});
}

newGame();
if (players[game.turn()] !== 'human') { paused = true; render(); } // a link never starts play by itself
