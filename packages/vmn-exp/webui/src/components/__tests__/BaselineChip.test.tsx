/** Plan 28 N3: an outer run's baseline chip — the server's text, coloured
 *  by its state, naming the run it compares against. */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import BaselineChip from "../BaselineChip";
import { CHIP, REF } from "./baselineFixture";

describe("the baseline chip", () => {
  it("shows the server's text, coloured by its state, naming its baseline", () => {
    render(<MemoryRouter><BaselineChip chip={CHIP} baseline={REF} href="/x" /></MemoryRouter>);
    const chip = screen.getByRole("link", { name: /▼ best_value from 2024-12/ });
    expect(chip).toHaveClass("baseline-chip", "baseline-worse");
    expect(chip).toHaveAttribute("href", "/x");
    expect(chip).toHaveAttribute("title", "vs @12 wf_41aa, the latest ended outer run alike");
  });

  it("counts the pairs, `5 of 39 paired`, when some keys have no value on a side (plan 31 §2)", () => {
    render(<BaselineChip chip={{ ...CHIP, paired: 5, total: 39 }} />);
    expect(screen.getByText(/5 of 39 paired/)).toBeInTheDocument();
  });

  it("says nothing of the pairs when every key paired", () => {
    render(<BaselineChip chip={{ ...CHIP, paired: 39, total: 39 }} />);
    expect(screen.queryByText(/paired/)).toBeNull();
  });

  it("says a pinned baseline is pinned, and is plain text without a link", () => {
    render(<BaselineChip chip={{ ...CHIP, state: "better", text: "▲ best_value" }} baseline={{ ...REF, source: "pinned" }} />);
    const chip = screen.getByText("▲ best_value");
    expect(chip.tagName).toBe("SPAN");
    expect(chip).toHaveClass("baseline-better");
    expect(chip.title).toBe("vs @12 wf_41aa, pinned with the tag baseline=true");
  });
});
