/** Plain data (mappings, lists, strings, numbers, bools, null) as block
 *  YAML, every string a JSON (double-quoted YAML) scalar: what the web
 *  writes back into an app's settings file (plan 28 P4). */

type Data = unknown;

const PLAIN_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
/** Plain words YAML 1.1 reads as a bool or null. */
const NOT_A_STRING = /^(true|false|yes|no|on|off|y|n|null)$/i;
const key = (k: string) => (PLAIN_KEY.test(k) && !NOT_A_STRING.test(k) ? k : JSON.stringify(k));

const isMap = (v: Data): v is Record<string, Data> => typeof v === "object" && v !== null && !Array.isArray(v);
const isEmpty = (v: Data) => (Array.isArray(v) ? v.length === 0 : isMap(v) && Object.keys(v).length === 0);
const nested = (v: Data) => (Array.isArray(v) || isMap(v)) && !isEmpty(v);

function scalar(v: Data): string {
  if (Array.isArray(v)) return "[]";
  if (isMap(v)) return "{}";
  return v === undefined ? "null" : JSON.stringify(v);
}

function lines(v: Data, indent: string): string[] {
  if (Array.isArray(v)) {
    return v.flatMap((item) => {
      if (!nested(item)) return [`${indent}- ${scalar(item)}`];
      const [first, ...rest] = lines(item, `${indent}  `);
      return [`${indent}- ${first.trimStart()}`, ...rest];
    });
  }
  return Object.entries(v as Record<string, Data>).flatMap(([k, item]) => (
    nested(item) ? [`${indent}${key(k)}:`, ...lines(item, `${indent}  `)] : [`${indent}${key(k)}: ${scalar(item)}`]
  ));
}

export function dumpYaml(value: Record<string, Data>): string {
  const out = lines(value, "");
  return out.length ? `${out.join("\n")}\n` : "";
}
