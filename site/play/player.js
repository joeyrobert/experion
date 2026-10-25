import { Chess } from './vendor/chess.js';
import { Board } from './board.js';
import { ENGINES, createEngine } from './engines.js';
import { loadOpenings } from './openings.js';
import { roundRobin, standings, eloFromScore, formatPoints } from './tournament.js';

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
let tour = null; // round-robin in progress or finished, see the tournament section below

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

const touring = () => !!(tour && tour.running);

function canHumanMove() {
  return !touring() && !thinking && !game.isGameOver() && players[game.turn()] === 'human' && !engineError;
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
  renderResult();
}

// Big result banner over the board once the game is decided; render() hides it again after
// Undo or New game because the game is no longer over.
function renderResult() {
  const el = $('result');
  el.innerHTML = '';
  if (!game.isGameOver() || engineError) { el.hidden = true; return; }
  const title = document.createElement('div');
  const sub = document.createElement('div');
  title.className = 'result-title';
  sub.className = 'result-sub';
  if (game.isCheckmate()) {
    const winner = game.turn() === 'w' ? 'b' : 'w';
    const label = playerLabel(winner);
    title.textContent = label === 'You' ? 'You win!' : label + ' wins';
    title.classList.add('win');
    sub.textContent = 'Checkmate \u00b7 ' + (winner === 'w' ? 'White' : 'Black') + ' delivered mate';
  } else {
    title.textContent = 'Draw';
    sub.textContent = game.isStalemate() ? 'Stalemate'
      : game.isThreefoldRepetition() ? 'Threefold repetition'
      : game.isInsufficientMaterial() ? 'Insufficient material'
      : 'Fifty-move rule';
  }
  el.append(title, sub);
  el.hidden = false;
}

function renderTags() {
  const top = board.orientation === 'w' ? 'b' : 'w';
  const bottom = board.orientation;
  for (const [el, color] of [[$('tag-top'), top], [$('tag-bottom'), bottom]]) {
    el.innerHTML = '';
    const swatch = document.createElement('span');
    swatch.className = 'swatch ' + (color === 'w' ? 'white' : 'black');
    swatch.setAttribute('aria-label', color === 'w' ? 'White' : 'Black');
    el.append(swatch, document.createTextNode(playerLabel(color)));
    el.classList.toggle('active', !game.isGameOver() && game.turn() === color);
  }
}

function renderControls() {
  const anyEngine = players.w !== 'human' || players.b !== 'human';
  $('pause').disabled = !anyEngine;
  $('pause').textContent = paused ? (game.history().length ? 'Resume' : 'Start') : 'Pause';
  $('pause').classList.toggle('active', paused);
  $('go').disabled = thinking || touring();
  for (const id of ['white', 'black', 'level', 'openings', 'new', 'undo', 'load-fen', 'tour-games']) $(id).disabled = touring();
  for (const box of $('tour-engines').querySelectorAll('input')) box.disabled = touring();
  $('tour-start').disabled = touring();
  $('tour-stop').disabled = !touring();
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
  if (touring()) {
    const line = openings[tour.games[tour.index].opening];
    return line && line.length > hist.length && hist.every((m, i) => m === line[i]) ? line[hist.length] : null;
  }
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
      else if (touring()) engineError = `${nameOf(id)} did not return a move.`;
    }
    render();
    afterMove();
  } catch (err) {
    if (token !== searchToken) return; // cancelled by undo, new game or a player change
    thinking = false;
    engineError = `${nameOf(id)} could not run: ${err.message}.` + (id.startsWith('bridge:') ? '' : ' Open this page over http(s), not from a file.');
    render();
    if (touring()) tournamentGameOver(side);
  }
}

function afterMove() {
  if (touring() && !engineError && game.history().length >= MAX_TOUR_PLIES) { tournamentGameOver(); return; }
  if (game.isGameOver() || engineError) {
    render();
    if (touring()) tournamentGameOver(engineError ? game.turn() : null);
    return;
  }
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

// ---- tournaments ------------------------------------------------------------------------------
//
// A round robin between the checked engines, played one game at a time on the main board at the
// strength and openings chosen above. Results survive a reload (localStorage), and a stopped or
// interrupted tournament resumes from the game it was on.

const MAX_TOUR_PLIES = 600; // adjudicate a draw after 300 moves
const TOUR_KEY = 'experion.tournament';
const TOUR_DEFAULT = ['experion', 'fruit', 'stash-21', 'stash-25'];
const unfinished = () => !!(tour && tour.index < tour.games.length);

function saveTour() {
  try {
    if (tour) localStorage.setItem(TOUR_KEY, JSON.stringify({ ...tour, running: false, timer: undefined }));
    else localStorage.removeItem(TOUR_KEY);
  } catch { /* storage unavailable */ }
}

function restoreTour() {
  try {
    const saved = JSON.parse(localStorage.getItem(TOUR_KEY));
    if (saved && Array.isArray(saved.ids) && Array.isArray(saved.games)) tour = { ...saved, running: false };
  } catch { /* nothing saved, or storage unavailable */ }
}

function fillTourEngines() {
  const box = $('tour-engines');
  const checked = new Set(tour ? tour.ids : [...box.querySelectorAll('input:checked')].map((i) => i.value));
  if (!box.children.length && !tour) TOUR_DEFAULT.forEach((id) => checked.add(id));
  box.innerHTML = '';
  for (const def of registry.values()) {
    const label = document.createElement('label');
    label.title = def.blurb || '';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = def.id;
    input.checked = checked.has(def.id);
    label.append(input, document.createTextNode(def.name));
    box.appendChild(label);
  }
}

function startTournament() {
  if (!unfinished()) {
    const ids = [...$('tour-engines').querySelectorAll('input:checked')].map((i) => i.value);
    if (ids.length < 2) { $('tour-progress').textContent = 'Pick at least two engines.'; return; }
    tour = {
      ids, games: roundRobin(ids, +$('tour-games').value, openings.length), index: 0,
      level: $('level').value, openings: $('openings').value, date: new Date().toISOString().slice(0, 10),
    };
  }
  const missing = tour.ids.filter((id) => !registry.has(id));
  if (missing.length) { $('tour-progress').textContent = 'Connect local engines first: ' + missing.join(', ') + '.'; return; }
  $('level').value = tour.level;
  $('openings').value = tour.openings;
  tour.running = true;
  saveTour();
  playTourGame();
}

function playTourGame() {
  const g = tour.games[tour.index];
  $('white').value = g.white;
  $('black').value = g.black;
  newGame();
  renderTournament();
}

function stopTournament() {
  if (!touring()) return;
  clearTimeout(tour.timer);
  tour.running = false;
  cancelSearch();
  paused = true;
  saveTour();
  render();
  renderTournament();
}

function drawReason() {
  if (game.isStalemate()) return 'stalemate';
  if (game.isThreefoldRepetition()) return 'repetition';
  if (game.isInsufficientMaterial()) return 'insufficient material';
  if (game.isDraw()) return 'fifty-move rule';
  return 'adjudicated after ' + MAX_TOUR_PLIES / 2 + ' moves';
}

// Records the game on the board. `loser` is the colour whose engine failed (it forfeits), if any.
function tournamentGameOver(loser = null) {
  const g = tour.games[tour.index];
  if (g.result) return;
  if (loser) { g.result = loser === 'w' ? '0-1' : '1-0'; g.reason = 'forfeit: ' + engineError; }
  else if (game.isCheckmate()) { g.result = game.turn() === 'w' ? '0-1' : '1-0'; g.reason = 'checkmate'; }
  else { g.result = '1/2-1/2'; g.reason = drawReason(); }
  g.moves = Math.ceil(game.history().length / 2);
  const headers = {
    Event: 'Experion web tournament', Site: location.origin + location.pathname, Date: tour.date.replace(/-/g, '.'),
    Round: String(tour.index + 1), White: nameOf(g.white), Black: nameOf(g.black), Result: g.result,
    TimeControl: $('level').selectedOptions[0].textContent, Termination: g.reason,
  };
  for (const [k, v] of Object.entries(headers)) game.setHeader(k, v);
  g.pgn = game.pgn();
  tour.index++;
  if (!unfinished()) tour.running = false;
  saveTour();
  render();
  renderTournament();
  if (touring()) tour.timer = setTimeout(() => { if (touring()) playTourGame(); }, 2500);
}

function renderTournament() {
  $('tour-start').textContent = unfinished() && tour.index > 0 ? 'Resume tournament' : 'Start tournament';
  const progress = $('tour-progress');
  const results = $('tour-results');
  if (!tour) {
    progress.textContent = 'Check two or more engines and press Start. Every game uses the strength and openings chosen above.';
    results.hidden = true;
    return;
  }
  const n = tour.games.length;
  const current = touring() ? tour.games[tour.index] : null;
  progress.textContent = current ? `Game ${tour.index + 1} of ${n}: ${nameOf(current.white)} vs ${nameOf(current.black)}`
    : unfinished() ? `Stopped after ${tour.index} of ${n} games.` : `Finished: all ${n} games played.`;
  results.hidden = false;
  $('tour-title').textContent = `Tournament · ${tour.index} of ${n} games`;

  const rows = standings(tour.ids, tour.games);
  const table = $('tour-table');
  table.innerHTML = '';
  const head = table.insertRow();
  const th = (text, cls) => { const c = document.createElement('th'); c.textContent = text; if (cls) c.className = cls; head.appendChild(c); };
  th('#'); th('Engine', 'name'); th('Pts'); th('Games');
  rows.forEach((_, i) => th(String(i + 1)));
  th('W-D-L'); th('Perf');
  rows.forEach((r, i) => {
    const tr = table.insertRow();
    if (current && (current.white === r.id || current.black === r.id)) tr.className = 'playing';
    const td = (text, cls) => { const c = tr.insertCell(); c.textContent = text; if (cls) c.className = cls; return c; };
    td(String(i + 1));
    td(nameOf(r.id) || r.id, 'name').title = (registry.get(r.id) || {}).blurb || '';
    td(formatPoints(r.points), 'pts');
    td(String(r.games));
    for (const opp of rows) {
      if (opp.id === r.id) { td('', 'self'); continue; }
      const v = r.vs.get(opp.id);
      td(v ? `${formatPoints(v.points)}/${v.games}` : '·');
    }
    td(`${r.w}-${r.d}-${r.l}`);
    const elo = eloFromScore(r.points, r.games);
    td(elo === null ? (r.games ? (r.points ? '+∞' : '−∞') : '') : (elo >= 0 ? '+' : '−') + Math.abs(Math.round(elo)));
  });

  const log = $('tour-log');
  log.innerHTML = '';
  tour.games.forEach((g, i) => {
    const li = document.createElement('li');
    const names = `${nameOf(g.white) || g.white} – ${nameOf(g.black) || g.black}`;
    li.textContent = g.result ? `${names}: ${g.result.replace('1/2-1/2', '½-½')} (${g.reason}, ${g.moves} moves)`
      : names + (current && i === tour.index ? ': playing' : '');
    if (!g.result) li.className = 'pending';
    log.appendChild(li);
  });
}

$('tour-start').onclick = startTournament;
$('tour-stop').onclick = stopTournament;
$('tour-pgn').onclick = () => copy(tour ? tour.games.filter((g) => g.pgn).map((g) => g.pgn).join('\n\n') + '\n' : '', $('tour-pgn'));
$('tour-clear').onclick = () => {
  if (touring()) stopTournament();
  tour = null;
  saveTour();
  fillTourEngines();
  render();
  renderTournament();
};

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
  if (!touring()) fillTourEngines();
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

restoreTour();
fillTourEngines();
renderTournament();
newGame();
if (players[game.turn()] !== 'human') { paused = true; render(); } // a link never starts play by itself
