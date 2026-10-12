const MAX_DISTANCE = 2;

/** Levenshtein distance between *a* and *b*. */
function distance(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

/** The candidate a typo most likely meant: one within edit distance 2, or one
 *  the typo is a prefix of; the nearest wins. Null when none is close. */
export function closest(name: string, candidates: string[]): string | null {
  let best: string | null = null;
  let bestDistance = Infinity;
  for (const c of candidates) {
    if (c === name) continue;
    const d = distance(name, c);
    if ((d <= MAX_DISTANCE || c.startsWith(name)) && d < bestDistance) {
      best = c;
      bestDistance = d;
    }
  }
  return best;
}
