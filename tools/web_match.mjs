#!/usr/bin/env node
// Strength check for the *browser* configuration: Experion's WebAssembly build (one thread, a
// fresh instance per move, fixed time per move) against another engine, from a set of opening
// lines with both colours, several games in parallel.
//
//   node tools/web_match.mjs --opp fruit|crafty --ms 300 [--games 48] [--procs 5]
//
// Fruit runs as its WebAssembly build. Crafty is not redistributable, so it runs natively
// through tools/match/uci_bridge. Results are printed as W-L-D from Experion's side.
import fs from 'node:fs';
import path from 'node:path';
import { fork, spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { Chess } from '../site/play/vendor/chess.js';
import { loadOpenings } from '../site/play/openings.js';
import { runEngine } from '../site/play/engine-core.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf('--' + n); return i >= 0 ? argv[i + 1] : d; };
const oppName = opt('opp', 'fruit');
const ms = +opt('ms', 300);
const games = +opt('games', 48);
const procs = +opt('procs', 5);
const wasm = (file) => WebAssembly.compile(fs.readFileSync(path.join(root, file)));

function uciScript(setup, moves, ms) {
  return ['uci', ...setup, 'isready', 'position startpos' + (moves.length ? ' moves ' + moves.join(' ') : ''), `go movetime ${ms}`, 'quit', ''].join('\n');
}

async function wasmEngine(file, setup) {
  const mod = await wasm(file);
  return async (moves) => {
    let best = null;
    runEngine(mod, uciScript(setup, moves, ms), (l) => { if (l.startsWith('bestmove')) best = l.split(/\s+/)[1]; });
    return best;
  };
}

function nativeEngine(cmd, cwd) {
  return (moves) => new Promise((resolve) => {
    const child = spawn(cmd[0], cmd.slice(1), { cwd, stdio: ['pipe', 'pipe', 'ignore'] });
    let buf = '';
    let done = false;
    const finish = (m) => { if (done) return; done = true; try { child.stdin.write('quit\n'); } catch { /* gone */ } setTimeout(() => child.kill(), 200); resolve(m); };
    child.stdout.on('data', (d) => {
      buf += d;
      for (const line of buf.split('\n')) if (line.startsWith('bestmove')) finish(line.split(/\s+/)[1]);
    });
    child.on('exit', () => finish(null));
    child.stdin.write(uciScript([], moves, ms));
  });
}

async function makeOpponent() {
  if (oppName === 'fruit') return wasmEngine('site/engines/fruit/fruit.wasm', []);
  if (oppName === 'crafty') {
    const dir = path.join(root, 'tools/match/Crafty-Chess-25.2');
    return nativeEngine([path.join(root, 'tools/match/uci_bridge'), '--needs-restart', path.join(dir, 'crafty252')], dir);
  }
  throw new Error('unknown opponent ' + oppName);
}

async function play(white, black, line) {
  const g = new Chess();
  const moves = [];
  const apply = (uci) => { g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }); moves.push(uci); };
  for (const u of line) apply(u);
  while (!g.isGameOver() && moves.length < 320) {
    const engine = g.turn() === 'w' ? white : black;
    const uci = await engine(moves);
    if (!uci || uci === '0000') return g.turn() === 'w' ? 0 : 1; // no move: treat as a loss for the mover
    try { apply(uci); } catch { return g.turn() === 'w' ? 1 : 0; } // illegal move loses (opponent already applied)
  }
  if (g.isCheckmate()) return g.turn() === 'w' ? 0 : 1; // side to move is mated
  return 0.5;
}

if (argv[0] === '--child') {
  const [, idx, n] = argv;
  const lines = loadOpenings(Chess);
  const exp = await wasmEngine('site/play/experion.wasm', ['setoption name Hash value 32']);
  const opp = await makeOpponent();
  for (let k = +idx; k < games; k += +n) {
    const line = lines[Math.floor(k / 2) % lines.length];
    const expWhite = k % 2 === 0;
    const r = expWhite ? await play(exp, opp, line) : await play(opp, exp, line);
    const score = expWhite ? r : 1 - r;
    process.send({ k, score });
  }
  process.exit(0);
} else {
  let w = 0, l = 0, d = 0;
  const t0 = Date.now();
  const kids = [];
  for (let i = 0; i < procs; i++) {
    const c = fork(fileURLToPath(import.meta.url), ['--child', String(i), String(procs), ...argv], { execArgv: ['--no-warnings'] });
    c.on('message', ({ score }) => {
      if (score === 1) w++; else if (score === 0) l++; else d++;
      const n = w + l + d;
      if (n % 4 === 0 || n === games) console.log(`${n}/${games}: +${w} =${d} -${l}  (${((w + d / 2) / n * 100).toFixed(1)}%)`);
    });
    kids.push(new Promise((res) => c.on('exit', res)));
  }
  await Promise.all(kids);
  const n = w + l + d;
  const p = (w + d / 2) / n;
  const elo = p > 0 && p < 1 ? (400 * Math.log10(p / (1 - p))).toFixed(0) : 'n/a';
  console.log(`Experion (browser build, ${ms} ms/move, 1 thread) vs ${oppName}: ${w}-${l}-${d} of ${n}, score ${(p * 100).toFixed(1)}%, Elo ${elo}, ${Math.round((Date.now() - t0) / 1000)} s`);
}
