// Web Worker for WebAssembly engines: one search per request, each on a fresh instance.
import { runEngine, compileEngine } from './engine-core.js';

const modules = new Map(); // wasm URL -> Promise<WebAssembly.Module>

self.onmessage = async (e) => {
  const { id, wasm, script } = e.data;
  try {
    if (!modules.has(wasm)) modules.set(wasm, compileEngine(wasm));
    const module = await modules.get(wasm);
    runEngine(module, script, (line) => self.postMessage({ id, type: 'line', line }));
    self.postMessage({ id, type: 'done' });
  } catch (err) {
    modules.delete(wasm);
    self.postMessage({ id, type: 'error', message: String(err && err.message || err) });
  }
};
