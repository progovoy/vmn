/** Pure utilities for leaderboard column ordering and pinning.
 *
 *  All functions are pure and return new arrays — none mutates its input.
 *  Designed to work with repeated URL params: `col=` drives `order`,
 *  `pin=` drives `pinned`. P0.7 and P0.8 wire these into the UI. */

/** Ordered column keys: pinned group first (in `order` sequence), then
 *  unpinned keys from `order`, then remaining `defaultKeys` in default order.
 *
 *  Keys in `order` or `pinned` that are absent from `defaultKeys` are silently
 *  dropped — hidden columns are not rendered even when pinned. */
export function orderedKeys(
  defaultKeys: readonly string[],
  order: readonly string[],
  pinned: readonly string[],
): string[] {
  const defaults = new Set(defaultKeys);
  const pinnedSet = new Set(pinned.filter((k) => defaults.has(k)));
  const inOrder = new Set(order.filter((k) => defaults.has(k)));

  const pinnedInOrder = order.filter((k) => pinnedSet.has(k));
  const pinnedRest = defaultKeys.filter((k) => pinnedSet.has(k) && !inOrder.has(k));

  const unpinnedInOrder = order.filter((k) => defaults.has(k) && !pinnedSet.has(k));
  const unpinnedRest = defaultKeys.filter((k) => !pinnedSet.has(k) && !inOrder.has(k));

  return [...pinnedInOrder, ...pinnedRest, ...unpinnedInOrder, ...unpinnedRest];
}

/** New `order` array after moving `key` by `delta` steps within its group
 *  (pinned keys stay among pinned, unpinned among unpinned), clamping at
 *  group edges so the key never crosses the boundary.
 *
 *  The returned array can be stored directly as the new `col=` URL params. */
export function moveKey(
  order: readonly string[],
  key: string,
  delta: number,
  defaultKeys: readonly string[],
  pinned: readonly string[],
): string[] {
  const rendered = orderedKeys(defaultKeys, order, pinned);
  const pinnedSet = new Set(pinned.filter((k) => new Set(defaultKeys).has(k)));

  const isPinned = pinnedSet.has(key);
  const group = rendered.filter((k) => pinnedSet.has(k) === isPinned);
  const idx = group.indexOf(key);
  if (idx === -1) return [...rendered];

  const newIdx = Math.max(0, Math.min(group.length - 1, idx + delta));
  if (newIdx === idx) return [...rendered];

  const newGroup = [...group];
  newGroup.splice(idx, 1);
  newGroup.splice(newIdx, 0, key);

  return isPinned
    ? [...newGroup, ...rendered.filter((k) => !pinnedSet.has(k))]
    : [...rendered.filter((k) => pinnedSet.has(k)), ...newGroup];
}

/** New `pinned` array with `key` added if absent, removed if present. */
export function togglePin(pinned: readonly string[], key: string): string[] {
  return pinned.includes(key)
    ? pinned.filter((k) => k !== key)
    : [...pinned, key];
}
