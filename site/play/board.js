// Dependency-free chess board: click-to-move and drag-and-drop, legal-move hints,
// last-move and check highlighting, flippable. Rules live elsewhere (chess.js); the
// board only asks `targetsFor(square)` and reports `onMove(from, to)`.

const FILES = 'abcdefgh';
// One filled glyph set for both colours (U+FE0E forces text rather than emoji rendering).
const GLYPH = { p: '♟︎', n: '♞︎', b: '♝︎', r: '♜︎', q: '♛︎', k: '♚︎' };

export class Board {
  constructor(root, { targetsFor, onMove }) {
    this.root = root;
    this.targetsFor = targetsFor;
    this.onMove = onMove;
    this.orientation = 'w';
    this.pieces = {}; // square -> {color, type}
    this.lastMove = null;
    this.checkSquare = null;
    this.selected = null;
    this.targets = [];
    this.locked = false; // no interaction (engine thinking, game over)
    this.drag = null;
    this.squares = {};
    this.build();
  }

  build() {
    this.root.classList.add('board');
    this.root.innerHTML = '';
    this.grid = document.createElement('div');
    this.grid.className = 'board-grid';
    this.root.appendChild(this.grid);
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        const sq = FILES[f] + (r + 1);
        const el = document.createElement('div');
        el.className = 'sq ' + ((f + r) % 2 === 0 ? 'dark' : 'light');
        el.dataset.sq = sq;
        this.grid.appendChild(el);
        this.squares[sq] = el;
      }
    }
    this.coords = document.createElement('div');
    this.coords.className = 'board-coords';
    this.root.appendChild(this.coords);
    this.grid.addEventListener('pointerdown', (e) => this.pointerDown(e));
    window.addEventListener('pointermove', (e) => this.pointerMove(e));
    window.addEventListener('pointerup', (e) => this.pointerUp(e));
    window.addEventListener('pointercancel', () => this.cancelDrag());
    this.layout();
  }

  // Place squares on the grid for the current orientation.
  layout() {
    const white = this.orientation === 'w';
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        const sq = FILES[f] + (r + 1);
        const el = this.squares[sq];
        el.style.gridColumn = (white ? f : 7 - f) + 1;
        el.style.gridRow = (white ? 7 - r : r) + 1;
      }
    }
    this.coords.innerHTML = '';
    for (let i = 0; i < 8; i++) {
      const file = document.createElement('span');
      file.className = 'coord file';
      file.textContent = FILES[white ? i : 7 - i];
      file.style.gridColumn = i + 1;
      const rank = document.createElement('span');
      rank.className = 'coord rank';
      rank.textContent = white ? 8 - i : i + 1;
      rank.style.gridRow = i + 1;
      this.coords.append(file, rank);
    }
  }

  setOrientation(color) {
    this.orientation = color;
    this.layout();
  }

  flip() {
    this.setOrientation(this.orientation === 'w' ? 'b' : 'w');
  }

  // pieces: array of 64 entries from chess.js board() ({square,type,color} or null)
  setPosition(boardArray) {
    this.pieces = {};
    for (const row of boardArray) for (const p of row) if (p) this.pieces[p.square] = { color: p.color, type: p.type };
    this.clearSelection();
    this.render();
  }

  setLastMove(from, to) { this.lastMove = from ? { from, to } : null; this.render(); }
  setCheck(square) { this.checkSquare = square; this.render(); }
  setLocked(v) { this.locked = v; if (v) this.clearSelection(); }

  render() {
    for (const [sq, el] of Object.entries(this.squares)) {
      el.classList.toggle('last', !!this.lastMove && (this.lastMove.from === sq || this.lastMove.to === sq));
      el.classList.toggle('check', this.checkSquare === sq);
      el.classList.toggle('selected', this.selected === sq);
      el.classList.toggle('target', this.targets.includes(sq));
      el.classList.toggle('capture', this.targets.includes(sq) && !!this.pieces[sq]);
      const p = this.pieces[sq];
      let piece = el.querySelector('.piece');
      if (!p) { if (piece) piece.remove(); continue; }
      if (!piece) { piece = document.createElement('span'); el.appendChild(piece); }
      piece.className = 'piece ' + (p.color === 'w' ? 'white' : 'black');
      piece.textContent = GLYPH[p.type];
    }
  }

  clearSelection() { this.selected = null; this.targets = []; this.render(); }

  select(sq) {
    this.selected = sq;
    this.targets = this.targetsFor(sq);
    this.render();
  }

  squareAt(x, y) {
    const el = document.elementFromPoint(x, y);
    const s = el && el.closest && el.closest('.sq');
    return s ? s.dataset.sq : null;
  }

  pointerDown(e) {
    if (this.locked || e.button > 0) return;
    const sq = this.squareAt(e.clientX, e.clientY);
    if (!sq) return;
    // Second click on a highlighted target completes a click-to-move.
    if (this.selected && this.targets.includes(sq)) {
      const from = this.selected;
      this.clearSelection();
      this.onMove(from, sq);
      return;
    }
    const targets = this.pieces[sq] ? this.targetsFor(sq) : [];
    if (!targets.length) { this.clearSelection(); return; }
    this.select(sq);
    const el = this.squares[sq].querySelector('.piece');
    const ghost = el.cloneNode(true);
    ghost.classList.add('ghost');
    const size = this.squares[sq].getBoundingClientRect().width;
    ghost.style.width = ghost.style.height = size + 'px';
    ghost.style.fontSize = size * 0.85 + 'px';
    document.body.appendChild(ghost);
    el.classList.add('dragging');
    this.drag = { from: sq, ghost, el, size, moved: false, startX: e.clientX, startY: e.clientY };
    this.positionGhost(e);
    e.preventDefault();
  }

  positionGhost(e) {
    const d = this.drag;
    d.ghost.style.transform = `translate(${e.clientX - d.size / 2}px, ${e.clientY - d.size / 2}px)`;
  }

  pointerMove(e) {
    if (!this.drag) return;
    if (Math.abs(e.clientX - this.drag.startX) + Math.abs(e.clientY - this.drag.startY) > 4) this.drag.moved = true;
    this.positionGhost(e);
  }

  pointerUp(e) {
    const d = this.drag;
    if (!d) return;
    this.cancelDrag();
    if (!d.moved) return; // plain click: keep the selection for click-to-move
    const to = this.squareAt(e.clientX, e.clientY);
    if (to && this.targets.includes(to)) {
      this.clearSelection();
      this.onMove(d.from, to);
    } else if (to !== d.from) {
      this.clearSelection();
    }
  }

  cancelDrag() {
    if (!this.drag) return;
    this.drag.ghost.remove();
    this.drag.el.classList.remove('dragging');
    this.drag = null;
  }
}
