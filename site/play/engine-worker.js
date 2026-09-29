// Web Worker: one search per request, each on a fresh instance of the engine.
import { runEngine, compileEngine } from './engine-core.js';

let modulePromise = null;

self.onmessage = async (e) => {
  const { id, script } = e.data;
  try {
    modulePromise ||= compileEngine(new URL('./experion.wasm', import.meta.url));
    const module = await modulePromise;
    runEngine(module, script, (line) => self.postMessage({ id, type: 'line', line }));
    self.postMessage({ id, type: 'done' });
  } catch (err) {
    modulePromise = null;
    self.postMessage({ id, type: 'error', message: String(err && err.message || err) });
  }
};
