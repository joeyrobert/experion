// Runs the Experion WebAssembly build against a preloaded UCI script.
//
// The module is a WASI command: it reads a script from stdin (EOF ends it) and writes its
// output to stdout. We provide the small set of WASI imports these engines need and stream
// stdout lines to a callback as they are written, so search info arrives live while the
// search is running. Works for any single-threaded WASI engine (Experion, Fruit, ...).

class ExitSignal {
  constructor(code) { this.code = code; }
}

export function runEngine(module, script, onLine) {
  const stdin = new TextEncoder().encode(script);
  let stdinPos = 0;
  const decoder = new TextDecoder();
  let pending = '';
  let memory;
  const view = () => new DataView(memory.buffer);
  const bytes = () => new Uint8Array(memory.buffer);

  const emit = (chunk) => {
    pending += chunk;
    let nl;
    while ((nl = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, nl).replace(/\r$/, '');
      pending = pending.slice(nl + 1);
      if (line) onLine(line);
    }
  };

  const argv = new TextEncoder().encode('experion\0');
  const t0 = performance.now();
  const wasi = {
    args_sizes_get: (argc, size) => { view().setUint32(argc, 1, true); view().setUint32(size, argv.length, true); return 0; },
    args_get: (argvPtr, buf) => { view().setUint32(argvPtr, buf, true); bytes().set(argv, buf); return 0; },
    environ_sizes_get: (count, size) => { view().setUint32(count, 0, true); view().setUint32(size, 0, true); return 0; },
    environ_get: () => 0,
    clock_time_get: (id, _precision, out) => {
      const ns = id === 0 ? BigInt(Date.now()) * 1000000n : BigInt(Math.round((performance.now() - t0 + 1) * 1e6));
      view().setBigUint64(out, ns, true);
      return 0;
    },
    fd_fdstat_get: (fd, out) => {
      const dv = view();
      for (let i = 0; i < 24; i++) dv.setUint8(out + i, 0);
      dv.setUint8(out, fd <= 2 ? 2 : 4); // character device
      dv.setBigUint64(out + 8, 0xffffffffffffffffn, true);
      return 0;
    },
    fd_fdstat_set_flags: () => 0,
    fd_read: (fd, iovs, iovsLen, nread) => {
      const dv = view();
      let total = 0;
      if (fd === 0) {
        for (let i = 0; i < iovsLen; i++) {
          const ptr = dv.getUint32(iovs + i * 8, true);
          const len = dv.getUint32(iovs + i * 8 + 4, true);
          const n = Math.min(len, stdin.length - stdinPos);
          bytes().set(stdin.subarray(stdinPos, stdinPos + n), ptr);
          stdinPos += n;
          total += n;
          if (n < len) break;
        }
      }
      dv.setUint32(nread, total, true);
      return 0;
    },
    fd_write: (fd, iovs, iovsLen, nwritten) => {
      const dv = view();
      let total = 0;
      for (let i = 0; i < iovsLen; i++) {
        const ptr = dv.getUint32(iovs + i * 8, true);
        const len = dv.getUint32(iovs + i * 8 + 4, true);
        if (fd === 1 || fd === 2) emit(decoder.decode(bytes().subarray(ptr, ptr + len), { stream: true }));
        total += len;
      }
      dv.setUint32(nwritten, total, true);
      return 0;
    },
    // Engines that touch the filesystem (opening books, logs) just see an empty sandbox.
    fd_close: () => 0,
    fd_seek: () => 70, // ESPIPE
    fd_prestat_get: () => 8, // EBADF: no preopened directories
    fd_prestat_dir_name: () => 8,
    path_open: () => 44, // ENOENT
    poll_oneoff: () => 52, // ENOSYS
    sched_yield: () => 0,
    proc_exit: (code) => { throw new ExitSignal(code); },
    random_get: (buf, len) => { crypto.getRandomValues(bytes().subarray(buf, buf + len)); return 0; },
  };

  const instance = new WebAssembly.Instance(module, { wasi_snapshot_preview1: wasi });
  memory = instance.exports.memory;
  try {
    instance.exports._start();
  } catch (e) {
    if (!(e instanceof ExitSignal)) throw e;
  }
  if (pending) onLine(pending);
}

export function compileEngine(url) {
  return WebAssembly.compileStreaming
    ? WebAssembly.compileStreaming(fetch(url)).catch(() => fetch(url).then((r) => r.arrayBuffer()).then(WebAssembly.compile))
    : fetch(url).then((r) => r.arrayBuffer()).then(WebAssembly.compile);
}
