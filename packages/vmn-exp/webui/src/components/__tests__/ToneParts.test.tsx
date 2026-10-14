/** One renderer for a line of toned parts (group counts, the job header). */
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import ToneParts from "../ToneParts";
import toneCss from "../toneParts.css?raw";
import { joinParts } from "../../util/toneParts";

const PARTS = [{ text: "4 runs", tone: "total" }, { text: "1 failed", tone: "failed" }, { text: "41/min" }];

describe("ToneParts", () => {
  it("joins the parts with dots, each toned one in its colour class", () => {
    const { container } = render(<ToneParts className="group-counts" parts={PARTS} />);
    const line = container.firstElementChild as HTMLElement;
    expect(line).toHaveClass("tone-parts", "group-counts");
    expect(line.textContent).toBe("4 runs · 1 failed · 41/min");
    expect(line.querySelector(".tone-failed")?.textContent).toBe("1 failed");
    expect(line.querySelectorAll("[class^='tone-']")).toHaveLength(2);
  });

  it("keeps the separators from a screen reader", () => {
    const { container } = render(<ToneParts parts={PARTS} />);
    const seps = [...container.querySelectorAll("[aria-hidden='true']")].map((s) => s.textContent);
    expect(seps).toEqual([" · ", " · "]);
  });

  it("has one colour rule per tone", () => {
    for (const tone of ["total", "running", "waiting", "stuck", "failed", "done"]) {
      expect(toneCss.match(new RegExp(`\\.tone-${tone}\\s*\\{`, "g"))).toHaveLength(1);
    }
  });
});

describe("joinParts", () => {
  it("joins the texts with a dot, or a given separator", () => {
    expect(joinParts(PARTS)).toBe("4 runs · 1 failed · 41/min");
    expect(joinParts(PARTS, ", ")).toBe("4 runs, 1 failed, 41/min");
  });
});
