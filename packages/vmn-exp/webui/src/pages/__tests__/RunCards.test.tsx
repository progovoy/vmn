/// <reference types="vite/client" />
/** Plan 20 E3 + E4: the run page's Metadata | Params | Metrics cards.
 *  jsdom lays nothing out, so the wrapping and grid rules are read from the
 *  component's stylesheet and the structure from the rendered DOM. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import css from "../runCards.css?raw";
import styles from "../../styles.css?raw";
import RunCards, { SHORT_PARAMS } from "../RunCards";
import { MetricsCard } from "../RunSections";

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "");

/** Declarations of the rule whose selector list names *selector*. */
function decls(sheet: string, selector: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [, head, body] of strip(sheet).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!head.split(",").map((s) => s.trim()).includes(selector)) continue;
    for (const d of body.split(";")) {
      const i = d.indexOf(":");
      if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
  }
  return out;
}

const SUMMARY = { last: 0.9, min: 0.2, max: 1, first: 1, mean: 0.7 };

describe("Metrics card summaries wrap cleanly (E3)", () => {
  it("keeps a metric's name and goal arrow together", () => {
    render(
      <MetricsCard metrics={{ grad_norm_l000: 0.2 }} summary={{ grad_norm_l000: SUMMARY }}
        schema={{ grad_norm_l000: { goal: "min" } }} />,
    );
    const name = screen.getByText("grad_norm_l000", { exact: false });
    expect(name).toHaveClass("metric-name");
    expect(name.querySelector(".metric-goal")?.textContent).toBe("↓");
    expect(decls(css, ".metric-name")["white-space"]).toBe("nowrap");
  });

  it("wraps the summary as whole label/value pairs", () => {
    render(
      <MetricsCard metrics={{ grad_norm_l000: 0.7 }} summary={{ grad_norm_l000: SUMMARY }} schema={null} />,
    );
    const line = screen.getByTestId("metric-summary-grad_norm_l000");
    const pairs = [...line.querySelectorAll(".metric-pair")].map((p) => p.textContent);
    expect(pairs).toEqual(["last 0.9", "min 0.2", "max 1", "first 1", "mean 0.7"]);
    // A separator wraps with the pair after it, never alone at a line start.
    const chunks = [...line.querySelectorAll(".metric-chunk")].map((c) => c.textContent);
    expect(chunks).toEqual(["last 0.9", " · min 0.2", " · max 1", " · first 1", " · mean 0.7"]);
    expect(decls(css, ".metric-chunk")["white-space"]).toBe("nowrap");
    expect(decls(css, ".metric-summary")["flex-wrap"]).toBe("wrap");
    // The value stays beside the name; the summary takes its own row under
    // both, and only a name too long for the card (420px) pushes the value down.
    expect(decls(css, ".metric-line")["flex-wrap"]).toBe("wrap");
    expect(decls(css, ".metric-values").display).toBe("contents");
    expect(decls(css, ".metric-summary")["flex-basis"]).toBe("100%");
  });

  it("moves the run-page metric rules out of the global stylesheet", () => {
    expect(decls(styles, ".metric-line")).toEqual({});
    expect(decls(styles, ".metric-summary")).toEqual({});
  });
});

const card = (name: string) => <div className="card"><h2>{name}</h2></div>;
const params = (n: number) => Object.fromEntries(Array.from({ length: n }, (_, i) => [`p${i}`, i]));
const show = (n: number) =>
  render(<RunCards metadata={card("Metadata")} params={params(n)} metrics={card("Metrics")} />);
const slotOf = (name: string) => screen.getByText(name).closest(".card")!.parentElement!;

describe("Metadata | Params | Metrics layout (E4)", () => {
  it("never stretches the cards to one row height", () => {
    expect(decls(css, ".run-cards")["align-items"]).toBe("start");
    expect(decls(css, ".run-cards-wide")["grid-column"]).toBe("1 / -1");
  });

  it("gives Metrics the full width under a short Params card", () => {
    show(3);
    expect(screen.getByText("Parameters")).toBeInTheDocument();
    expect(slotOf("Metrics")).toHaveClass("run-cards-wide");
  });

  it("stacks Metrics under Metadata beside a long Params card", () => {
    show(SHORT_PARAMS + 1);
    const stack = slotOf("Metrics");
    expect(stack).toHaveClass("run-cards-col");
    expect(stack).toContainElement(screen.getByText("Metadata"));
    expect(stack).not.toContainElement(screen.getByText("Parameters"));
  });

  it("sets Metadata and Metrics side by side without params", () => {
    show(0);
    expect(screen.queryByText("Parameters")).toBeNull();
    expect(slotOf("Metrics")).toHaveClass("run-cards");
    expect(slotOf("Metadata")).toHaveClass("run-cards");
  });
});
