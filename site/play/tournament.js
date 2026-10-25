// Round-robin tournament bookkeeping for the play page: schedule, results, standings and PGN.
// Pure data, no DOM; player.js plays the games on the main board.

// Every pair meets gamesPerPair times. Games come in colour-swapped couples that share one
// opening (`opening` indexes into a shuffled list), and rounds follow the circle method so each
// engine plays about as often as every other one throughout the event.
export function roundRobin(ids, gamesPerPair, openingCount) {
  const n = ids.length;
  const seats = n % 2 ? [...ids, null] : [...ids];
  const rounds = [];
  for (let r = 0; r < seats.length - 1; r++) {
    const round = [];
    for (let i = 0; i < seats.length / 2; i++) {
      const a = seats[i];
      const b = seats[seats.length - 1 - i];
      if (a !== null && b !== null) round.push(r % 2 ? [b, a] : [a, b]);
    }
    rounds.push(round);
    seats.splice(1, 0, seats.pop());
  }
  const order = shuffled([...Array(Math.max(openingCount, 1)).keys()]);
  const games = [];
  let nextOpening = 0;
  for (let cycle = 0; cycle * 2 < gamesPerPair; cycle++) {
    for (const round of rounds) {
      for (const [a, b] of round) {
        const opening = order[nextOpening++ % order.length];
        games.push({ white: a, black: b, opening, result: null });
        if (cycle * 2 + 1 < gamesPerPair) games.push({ white: b, black: a, opening, result: null });
      }
    }
  }
  return games;
}

function shuffled(list) {
  for (let i = list.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [list[i], list[j]] = [list[j], list[i]];
  }
  return list;
}

const POINTS = { '1-0': [1, 0], '0-1': [0, 1], '1/2-1/2': [0.5, 0.5] };

// Rows sorted by points, then Sonneborn-Berger, then wins; `vs` holds the score against each opponent.
export function standings(ids, games) {
  const rows = new Map(ids.map((id) => [id, { id, points: 0, games: 0, w: 0, d: 0, l: 0, sb: 0, vs: new Map() }]));
  const done = games.filter((g) => g.result);
  for (const g of done) {
    const [pw, pb] = POINTS[g.result];
    for (const [id, opp, p] of [[g.white, g.black, pw], [g.black, g.white, pb]]) {
      const row = rows.get(id);
      row.points += p;
      row.games++;
      if (p === 1) row.w++; else if (p === 0) row.l++; else row.d++;
      const v = row.vs.get(opp) || { points: 0, games: 0 };
      v.points += p;
      v.games++;
      row.vs.set(opp, v);
    }
  }
  for (const row of rows.values()) {
    for (const [opp, v] of row.vs) row.sb += v.points * rows.get(opp).points;
  }
  return [...rows.values()].sort((a, b) => b.points - a.points || b.sb - a.sb || b.w - a.w);
}

// Elo difference implied by a score fraction, or null when it is 0% or 100%.
export function eloFromScore(points, games) {
  if (!games) return null;
  const s = points / games;
  if (s <= 0 || s >= 1) return null;
  return -400 * Math.log10(1 / s - 1);
}

export function formatPoints(p) {
  const whole = Math.floor(p);
  const half = p - whole >= 0.5;
  return half ? (whole ? whole + '½' : '½') : String(whole);
}
