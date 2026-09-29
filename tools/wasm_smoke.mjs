// Smoke test for the browser engine: node tools/wasm_smoke.mjs [path/to/experion.wasm]
// Loads the WebAssembly build through the same runner the site uses and checks that it
// identifies itself, answers isready, evaluates a known position and returns a legal move.
import fs from 'node:fs';
import { runEngine } from '../site/play/engine-core.js';

const file = process.argv[2] || new URL('../site/play/experion.wasm', import.meta.url);
const module = await WebAssembly.compile(fs.readFileSync(file));
const lines = [];
runEngine(module, [
  'uci', 'isready',
  'position startpos moves e2e4 e7e5',
  'go depth 8',
  'position fen 4k3/8/8/8/8/8/8/R3K3 w Q - 0 1',
  'nnueeval',
  'quit', '',
].join('\n'), (l) => lines.push(l));

const fail = (msg) => { console.error('FAIL:', msg); console.error(lines.join('\n')); process.exit(1); };
if (!lines.some((l) => l.startsWith('id name Experion'))) fail('no id line');
if (!lines.includes('readyok')) fail('no readyok');
const best = lines.find((l) => l.startsWith('bestmove'));
if (!best || !/^bestmove [a-h][1-8][a-h][1-8]/.test(best)) fail('no bestmove');
const nn = lines.find((l) => l.startsWith('info string nnue'));
if (!nn || parseInt(nn.split(' ').pop(), 10) < 300) fail('a rook up should evaluate above +300, got: ' + nn);
console.log('ok:', best, '|', nn);
