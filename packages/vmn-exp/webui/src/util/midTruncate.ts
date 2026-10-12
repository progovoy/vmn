const TAIL = 8;

/** *text* cut to *max* chars in the middle: the head, `…`, and the last 8
 *  chars (a verstr's hash tail is what tells two runs apart). */
export function midTruncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const head = Math.max(0, max - TAIL - 1);
  return `${text.slice(0, head)}…${text.slice(-TAIL)}`;
}
