"""JavaScript injected by uiload.browser (kept apart so browser.py stays Python)."""

# Installed before any page script: collects every long task from page start.
LONGTASK_INIT = """
window.__vmnLongTasks = [];
try {
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__vmnLongTasks.push(e.duration);
  }).observe({ type: "longtask", buffered: true });
} catch (e) {}
"""

TOKEN_INIT = "sessionStorage.setItem('vmn_token', %s);"

# Virtualized rows carry data-row-index; the scroll container is .tbl-scroll.
ROW_SELECTOR = 'table[aria-label="experiments"] tbody tr[data-row-index]'

# Scroll the leaderboard down a viewport per frame for durationMs; at the bottom
# wait for more pages, and once nothing more comes start again from the top.
SCROLL = """
async (durationMs) => {
  const el = document.querySelector(".tbl-scroll");
  const frame = () => new Promise((r) => requestAnimationFrame(r));
  window.__vmnLongTasks = [];
  let maxIdx = -1;
  let idleFrames = 0;
  const seen = () => {
    for (const tr of el.querySelectorAll("tr[data-row-index]"))
      maxIdx = Math.max(maxIdx, Number(tr.dataset.rowIndex));
  };
  el.scrollTop = 0;
  const end = performance.now() + durationMs;
  while (performance.now() < end) {
    await frame();
    seen();
    const bottom = el.scrollHeight - el.clientHeight;
    if (el.scrollTop >= bottom - 1) {
      idleFrames += 1;
      if (idleFrames > 30) { el.scrollTop = 0; idleFrames = 0; }
    } else {
      idleFrames = 0;
      el.scrollTop = Math.min(bottom, el.scrollTop + el.clientHeight);
    }
  }
  await new Promise((r) => setTimeout(r, 100));
  seen();
  return { longtasks: window.__vmnLongTasks.slice(), rowsSeen: maxIdx + 1 };
}
"""

# A uPlot canvas inside a Run page metric chart, laid out with a real size.
CHART_SELECTOR = '[data-testid="metric-chart"]'
CHART_PAINTED = """
() => {
  const c = document.querySelector('[data-testid="metric-chart"] canvas');
  return !!c && c.width > 0 && c.height > 0;
}
"""

# The leaderboard subtitle: "N runs" or "shown of N runs" (N = the filtered total).
PAGE_TOTAL = """
() => {
  const t = document.querySelector(".page-sub")?.textContent || "";
  const m = t.match(/(\\d+) runs/);
  return m ? Number(m[1]) : null;
}
"""

PAGE_TOTAL_IS = "(total) => (" + PAGE_TOTAL + ")() === total"
PAGE_TOTAL_SHOWN = "() => (" + PAGE_TOTAL + ")() !== null"

VISIBLE_PILLS = """
() => [...document.querySelectorAll('table[aria-label="experiments"] tbody .status-pill')]
  .map((e) => [...e.classList].find((c) => c !== "status-pill"))
"""

HEAP_BYTES = "() => (performance.memory ? performance.memory.usedJSHeapSize : null)"
