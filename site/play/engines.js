// Engine registry and adapters. Every adapter exposes the same small interface:
//
//   search({ startFen, moves, limit }, onInfo) -> Promise<uci move | null>
//   cancel()   abandon the running search (the promise rejects with Error('cancelled'))
//
// startFen is null for the standard start position, moves are UCI strings, limit is
// {depth} or {movetime} in milliseconds. onInfo receives {depth, score, scoreType, nps, pv[]}.
//
// Adapters: UCI engines compiled to WebAssembly (Experion, Fruit), the CeruleanJS web worker
// (XBoard protocol) and an optional local bridge for native engines (see tools/engine-bridge.mjs).

export const ENGINES = [
  {
    id: 'experion', name: 'Experion', kind: 'uci-wasm', wasm: 'experion.wasm',
    setup: ['setoption name Hash value 32'],
    blurb: 'NNUE evaluation, written in Crystal',
  },
  {
    id: 'fruit', name: 'Fruit 2.1', kind: 'uci-wasm', wasm: '../engines/fruit/fruit.wasm',
    setup: [],
    blurb: 'Fabien Letouzey, 2005 (GPL)',
  },
  {
    id: 'cerulean', name: 'CeruleanJS', kind: 'xboard-js', worker: '../engines/ceruleanjs/ceruleanjs.js',
    blurb: 'JavaScript, with an opening book (GPL)',
  },
];

export function createEngine(def, extra = {}) {
  switch (def.kind) {
    case 'uci-wasm': return new UciWasmEngine(def);
    case 'xboard-js': return new XboardJsEngine(def);
    case 'bridge': return new BridgeEngine(def, extra.bridgeUrl);
    default: throw new Error('unknown engine kind ' + def.kind);
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
      case 'score': info.scoreType = t[++i]; info.score = +t[++i]; break;
      case 'pv': info.pv = t.slice(i + 1); i = t.length; break;
      default: break;
    }
  }
  return info;
}

function uciScript(def, { startFen, moves, limit }) {
  const position = (startFen ? `position fen ${startFen}` : 'position startpos') + (moves.length ? ` moves ${moves.join(' ')}` : '');
  const go = limit.depth ? `go depth ${limit.depth}` : `go movetime ${limit.movetime}`;
  return ['uci', ...(def.setup || []), 'isready', position, go, 'quit', ''].join('\n');
}

// A promise that can be cancelled; shared bookkeeping for the adapters below.
class Pending {
  constructor(onInfo) {
    this.promise = new Promise((resolve, reject) => { this.resolve = resolve; this.reject = reject; });
    this.onInfo = onInfo;
  }
}

// One search per request, each on a fresh instance of the module inside a worker.
class UciWasmEngine {
  constructor(def) {
    this.def = def;
    this.id = 0;
    this.pending = null;
    this.wasmUrl = new URL(def.wasm, import.meta.url).href;
    this.spawn();
  }

  spawn() {
    this.worker = new Worker(new URL('./engine-worker.js', import.meta.url), { type: 'module' });
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
      p.resolve(p.best && p.best !== '0000' && p.best !== '(none)' ? p.best : null);
    } else if (msg.type === 'error') {
      this.fail(new Error(msg.message));
    }
  }

  fail(err) {
    const p = this.pending;
    this.pending = null;
    if (p) p.reject(err);
  }

  search(request, onInfo) {
    if (this.pending) this.cancel();
    const p = new Pending(onInfo);
    p.id = ++this.id;
    p.best = null;
    this.pending = p;
    this.worker.postMessage({ id: p.id, wasm: this.wasmUrl, script: uciScript(this.def, request) });
    return p.promise;
  }

  cancel() {
    const p = this.pending;
    this.pending = null;
    this.worker.terminate();
    this.spawn();
    if (p) p.reject(new Error('cancelled'));
  }
}

// CeruleanJS runs as a classic worker that speaks XBoard over postMessage.
// Its time control is derived from `level`/`time` (`st` is overridden inside `go`), so a
// per-move budget is expressed as 100 moves in a proportional base time.
class XboardJsEngine {
  constructor(def) {
    this.def = def;
    this.url = new URL(def.worker, import.meta.url).href;
    this.pending = null;
    this.spawn();
  }

  spawn() {
    this.worker = new Worker(this.url);
    this.worker.onmessage = (e) => this.onLine(String(e.data));
    this.worker.onerror = (e) => this.fail(new Error(e.message || 'CeruleanJS worker failed'));
  }

  send(cmd) { this.worker.postMessage(cmd); }

  onLine(text) {
    const p = this.pending;
    if (!p) return;
    for (const line of text.split('\n')) {
      if (line.startsWith('move ')) {
        this.pending = null;
        p.resolve(line.slice(5).trim());
        return;
      }
      if (line.startsWith('Illegal move')) { this.fail(new Error(line)); return; }
    }
  }

  fail(err) {
    const p = this.pending;
    this.pending = null;
    if (p) p.reject(err);
  }

  search({ startFen, moves, limit }, onInfo) {
    if (this.pending) this.cancel();
    const p = new Pending(onInfo);
    this.pending = p;
    const ms = limit.depth ? 10000 : limit.movetime;
    const baseSec = Math.max(1, Math.round(ms / 10));
    const level = `100 ${Math.floor(baseSec / 60)}:${String(baseSec % 60).padStart(2, '0')} 0`;
    this.send('xboard');
    this.send('new');
    if (startFen) this.send('setboard ' + startFen);
    this.send('force');
    for (const m of moves) this.send(m);
    if (limit.depth) this.send('sd ' + limit.depth);
    this.send('level ' + level);
    this.send('time 1000000');
    this.send('go');
    return p.promise;
  }

  cancel() {
    const p = this.pending;
    this.pending = null;
    this.worker.terminate();
    this.spawn();
    if (p) p.reject(new Error('cancelled'));
  }
}

// Native engines exposed by tools/engine-bridge.mjs on the user's own machine.
class BridgeEngine {
  constructor(def, baseUrl) {
    this.def = def;
    this.baseUrl = baseUrl;
    this.abort = null;
  }

  async search(request, onInfo) {
    if (this.abort) this.cancel();
    const controller = new AbortController();
    this.abort = controller;
    let best = null;
    try {
      const res = await fetch(this.baseUrl + '/search', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ engine: this.def.remoteId, ...request }),
        signal: controller.signal,
      });
      if (!res.ok) throw new Error('bridge returned ' + res.status);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          if (line.startsWith('bestmove')) best = line.split(/\s+/)[1];
          else if (line.startsWith('info depth')) onInfo && onInfo(parseInfo(line));
        }
      }
    } catch (err) {
      if (controller.signal.aborted) throw new Error('cancelled');
      throw err;
    } finally {
      if (this.abort === controller) this.abort = null;
    }
    return best && best !== '0000' && best !== '(none)' ? best : null;
  }

  cancel() {
    if (this.abort) this.abort.abort();
    this.abort = null;
  }
}
