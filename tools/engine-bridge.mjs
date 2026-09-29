#!/usr/bin/env node
// Local engine bridge: lets the web player use native engines installed on this computer
// (for example Crafty, or the multi-threaded native Experion).
//
//   node tools/engine-bridge.mjs [--port 8787] [--config tools/engine-bridge.json]
//
// then, on the play page, press "Local engines" and accept the default URL. Engines are
// configured by you in a JSON file (see tools/engine-bridge.example.json); the bridge only ever
// runs the commands listed there, listens on 127.0.0.1 only, and only answers pages from the
// allowed origins. Nothing is uploaded anywhere: the page talks to this process on your machine.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const opt = (name, fallback) => { const i = args.indexOf('--' + name); return i >= 0 ? args[i + 1] : fallback; };
const port = +opt('port', 8787);
const configPath = path.resolve(root, opt('config', 'tools/engine-bridge.json'));
const allowedOrigins = [
  'https://joeyrobert.github.io',
  /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/,
  ...args.filter((a, i) => args[i - 1] === '--allow-origin'),
];

if (!fs.existsSync(configPath)) {
  console.error(`No config at ${configPath}. Copy tools/engine-bridge.example.json to tools/engine-bridge.json and edit it.`);
  process.exit(1);
}
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const engines = new Map(config.engines.map((e) => [e.id, e]));

const originAllowed = (origin) => !origin || allowedOrigins.some((o) => (o instanceof RegExp ? o.test(origin) : o === origin));

const FEN = /^[pnbrqkPNBRQK1-8/]+ [wb] (-|[KQkq]+) (-|[a-h][36]) \d+ \d+$/;
const MOVE = /^[a-h][1-8][a-h][1-8][qrbn]?$/;

function script(engine, { startFen, moves, limit }) {
  const lines = ['uci'];
  for (const [k, v] of Object.entries(engine.options || {})) lines.push(`setoption name ${k} value ${v}`);
  lines.push('isready');
  lines.push(startFen ? `position fen ${startFen}` : 'position startpos');
  if (moves.length) lines[lines.length - 1] += ' moves ' + moves.join(' ');
  lines.push(limit.depth ? `go depth ${limit.depth}` : `go movetime ${limit.movetime}`);
  return lines.join('\n') + '\n';
}

function cors(req, res) {
  const origin = req.headers.origin;
  res.setHeader('Access-Control-Allow-Origin', origin || '*');
  res.setHeader('Access-Control-Allow-Headers', 'content-type');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Private-Network', 'true');
  res.setHeader('Vary', 'Origin');
}

const server = http.createServer((req, res) => {
  cors(req, res);
  if (!originAllowed(req.headers.origin)) { res.writeHead(403).end('origin not allowed'); return; }
  if (req.method === 'OPTIONS') { res.writeHead(204).end(); return; }

  if (req.method === 'GET' && req.url === '/engines') {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify([...engines.values()].map((e) => ({ id: e.id, name: e.name }))));
    return;
  }

  if (req.method === 'POST' && req.url === '/search') {
    let body = '';
    req.on('data', (d) => { body += d; if (body.length > 20000) req.destroy(); });
    req.on('end', () => {
      let q;
      try { q = JSON.parse(body); } catch { res.writeHead(400).end('bad json'); return; }
      const engine = engines.get(q.engine);
      const limit = q.limit || {};
      const ok = engine && Array.isArray(q.moves) && q.moves.every((m) => MOVE.test(m)) &&
        (q.startFen == null || FEN.test(q.startFen)) &&
        ((Number.isInteger(limit.depth) && limit.depth > 0 && limit.depth < 100) ||
         (Number.isInteger(limit.movetime) && limit.movetime > 0 && limit.movetime <= 600000));
      if (!ok) { res.writeHead(400).end('bad request'); return; }

      const [cmd, ...cmdArgs] = engine.cmd.map((c, i) => (i === 0 || c.startsWith('-') ? c : path.resolve(root, c)));
      const child = spawn(path.resolve(root, cmd), cmdArgs, { cwd: path.resolve(root, engine.cwd || '.'), stdio: ['pipe', 'pipe', 'ignore'] });
      res.writeHead(200, { 'content-type': 'text/plain', 'cache-control': 'no-store' });
      let buf = '';
      let done = false;
      const finish = () => { if (done) return; done = true; try { child.stdin.write('quit\n'); } catch { /* gone */ } setTimeout(() => child.kill(), 300); res.end(); };
      child.stdout.on('data', (d) => {
        buf += d;
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (line.startsWith('info depth') || line.startsWith('bestmove')) res.write(line + '\n');
          if (line.startsWith('bestmove')) finish();
        }
      });
      child.on('exit', finish);
      child.on('error', (e) => { console.error(`cannot start ${engine.id}: ${e.message}`); finish(); });
      res.on('close', () => { if (!done) { done = true; child.kill(); } });
      child.stdin.write(script(engine, { startFen: q.startFen, moves: q.moves, limit }));
    });
    return;
  }

  res.writeHead(404).end();
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Engine bridge on http://127.0.0.1:${port} with ${engines.size} engine(s): ${[...engines.keys()].join(', ')}`);
});
