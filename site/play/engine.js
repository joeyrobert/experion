// Promise wrapper around the engine worker. One search per call; cancel() abandons the
// running search by replacing the worker (searches are pure computation, so this is safe).

export class Engine {
  constructor() {
    this.id = 0;
    this.spawn();
  }

  spawn() {
    this.worker = new Worker(new URL('./engine-worker.js', import.meta.url), { type: 'module' });
    this.pending = null;
    this.worker.onmessage = (e) => this.onMessage(e.data);
    this.worker.onerror = (e) => this.fail(new Error(e.message || 'engine worker failed'));
  }

  onMessage(msg) {
    const p = this.pending;
    if (!p || msg.id !== p.id) return;
    if (msg.type === 'line') {
      if (msg.line.startsWith('bestmove')) p.best = msg.line.split(/\s+/)[1];
      else if (msg.line.startsWith('info depth')) p.onInfo && p.onInfo(parseInfo(msg.line));
    } else if (msg.type === 'done') {
      this.pending = null;
      p.resolve(p.best && p.best !== '0000' ? p.best : null);
    } else if (msg.type === 'error') {
      this.fail(new Error(msg.message));
    }
  }

  fail(err) {
    const p = this.pending;
    this.pending = null;
    if (p) p.reject(err);
  }

  // startFen: null for the standard start position. moves: UCI strings. limit: {movetime} or {depth}.
  search({ startFen, moves, limit }, onInfo) {
    if (this.pending) this.cancel();
    const id = ++this.id;
    const position = (startFen ? `position fen ${startFen}` : 'position startpos') + (moves.length ? ` moves ${moves.join(' ')}` : '');
    const go = limit.depth ? `go depth ${limit.depth}` : `go movetime ${limit.movetime}`;
    const script = ['uci', 'setoption name Hash value 32', 'isready', position, go, 'quit', ''].join('\n');
    return new Promise((resolve, reject) => {
      this.pending = { id, resolve, reject, onInfo, best: null };
      this.worker.postMessage({ id, script });
    });
  }

  cancel() {
    const p = this.pending;
    this.worker.terminate();
    this.spawn();
    if (p) p.reject(new Error('cancelled'));
  }
}

export function parseInfo(line) {
  const t = line.split(/\s+/);
  const info = { pv: [] };
  for (let i = 1; i < t.length; i++) {
    switch (t[i]) {
      case 'depth': info.depth = +t[++i]; break;
      case 'nodes': info.nodes = +t[++i]; break;
      case 'nps': info.nps = +t[++i]; break;
      case 'time': info.time = +t[++i]; break;
      case 'score':
        info.scoreType = t[++i];
        info.score = +t[++i];
        break;
      case 'pv': info.pv = t.slice(i + 1); i = t.length; break;
      default: break;
    }
  }
  return info;
}
