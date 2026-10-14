/** A line of parts, some toned in a status colour (a group's counts, a
 *  job's progress). */
export interface TonePart {
  text: string;
  tone?: string;
}

/** The parts' texts as one line: `16 runs · 2 running`. */
export const joinParts = (parts: readonly TonePart[], sep = " · ") => parts.map((p) => p.text).join(sep);
