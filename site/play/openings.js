// Well-known opening lines (SAN). With "random lines" selected, engines start a new game by
// following one of these, so engine-vs-engine games do not repeat. Lines are validated against
// the rules engine at load time, and any that do not parse are dropped.
const SAN_LINES = [
  '1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7',
  '1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6',
  '1. e4 e5 2. Nf3 Nc6 3. d4 exd4 4. Nxd4 Nf6 5. Nxc6 bxc6',
  '1. e4 e5 2. Nf3 Nf6 3. Nxe5 d6 4. Nf3 Nxe4 5. d4 d5',
  '1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6',
  '1. e4 c5 2. Nf3 Nc6 3. d4 cxd4 4. Nxd4 g6 5. Nc3 Bg7',
  '1. e4 c5 2. Nf3 e6 3. d4 cxd4 4. Nxd4 Nc6 5. Nc3 Qc7',
  '1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 Bf5 5. Ng3 Bg6',
  '1. e4 e6 2. d4 d5 3. Nc3 Nf6 4. Bg5 Be7 5. e5 Nfd7',
  '1. e4 d5 2. exd5 Qxd5 3. Nc3 Qa5 4. d4 Nf6 5. Nf3 c6',
  '1. e4 d6 2. d4 Nf6 3. Nc3 g6 4. f4 Bg7 5. Nf3 O-O',
  '1. d4 d5 2. c4 e6 3. Nc3 Nf6 4. Bg5 Be7 5. e3 O-O',
  '1. d4 d5 2. c4 c6 3. Nf3 Nf6 4. Nc3 dxc4 5. a4 Bf5',
  '1. d4 d5 2. c4 dxc4 3. Nf3 Nf6 4. e3 e6 5. Bxc4 c5',
  '1. d4 Nf6 2. c4 g6 3. Nc3 Bg7 4. e4 d6 5. Nf3 O-O',
  '1. d4 Nf6 2. c4 e6 3. Nc3 Bb4 4. e3 O-O 5. Bd3 d5',
  '1. d4 Nf6 2. c4 e6 3. Nf3 b6 4. g3 Bb7 5. Bg2 Be7',
  '1. d4 Nf6 2. Nf3 g6 3. g3 Bg7 4. Bg2 O-O 5. O-O d6',
  '1. c4 e5 2. Nc3 Nf6 3. Nf3 Nc6 4. g3 d5 5. cxd5 Nxd5',
  '1. c4 c5 2. Nf3 Nf6 3. Nc3 Nc6 4. g3 g6 5. Bg2 Bg7',
  '1. Nf3 d5 2. g3 Nf6 3. Bg2 e6 4. O-O Be7 5. d3 O-O',
  '1. Nf3 Nf6 2. c4 g6 3. Nc3 Bg7 4. e4 d6 5. d4 O-O',
  '1. e4 e5 2. Nc3 Nf6 3. f4 d5 4. fxe5 Nxe4 5. Nf3 Be7',
  '1. e4 e5 2. f4 exf4 3. Nf3 g5 4. h4 g4 5. Ne5 Nf6',
  '1. d4 f5 2. g3 Nf6 3. Bg2 e6 4. Nf3 Be7 5. O-O O-O',
  '1. b3 e5 2. Bb2 Nc6 3. e3 d5 4. Bb5 Bd6 5. f4 Qh4+',
];

export function loadOpenings(Chess) {
  const lines = [];
  for (const text of SAN_LINES) {
    const g = new Chess();
    const tokens = text.split(/\s+/).filter((t) => !/^\d+\.$/.test(t));
    const uci = [];
    try {
      for (const san of tokens) {
        const m = g.move(san);
        uci.push(m.from + m.to + (m.promotion || ''));
      }
      lines.push(uci);
    } catch { /* drop malformed line */ }
  }
  return lines;
}
