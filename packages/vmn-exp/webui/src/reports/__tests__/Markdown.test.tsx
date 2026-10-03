import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Markdown } from "../Markdown";

describe("Markdown", () => {
  it("escapes raw HTML", () => {
    const { container } = render(<Markdown source={'<script>x()</script><b id="raw">hi</b>'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("#raw")).toBeNull();
  });

  it("opens links in a new tab safely", () => {
    render(<Markdown source="[site](https://example.com)" />);
    const a = screen.getByRole("link", { name: "site" });
    expect(a).toHaveAttribute("target", "_blank");
    expect(a).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders external images as links", () => {
    const { container } = render(<Markdown source="![pic](https://evil.com/x.png)" />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("link", { name: "pic" })).toHaveAttribute("href", "https://evil.com/x.png");
  });

  it("resolves vmn:// images", () => {
    const resolveMedia = vi.fn(() => "/api/media/a.png");
    const { container } = render(
      <Markdown source="![m](vmn://app/v1/media/a.png)" resolveMedia={resolveMedia} />,
    );
    expect(resolveMedia).toHaveBeenCalledWith("vmn://app/v1/media/a.png");
    expect(container.querySelector("img")).toHaveAttribute("src", "/api/media/a.png");
  });

  it("adds slug anchors to headings", () => {
    const { container } = render(<Markdown source={"# Hello World\n\n## Hello World"} />);
    const hs = container.querySelectorAll("h1, h2");
    expect(hs[0]).toHaveAttribute("id", "hello-world");
    expect(hs[1]).toHaveAttribute("id", "hello-world-1");
  });

  it("shows a table of contents only with more than 3 headings", () => {
    const { rerender } = render(<Markdown source={"# a\n# b\n# c"} />);
    expect(screen.queryByRole("navigation", { name: /contents/i })).toBeNull();
    rerender(<Markdown source={"# a\n# b\n# c\n## d"} />);
    const nav = screen.getByRole("navigation", { name: /contents/i });
    expect(nav.querySelector('a[href="#d"]')).not.toBeNull();
  });

  it("passes parsed vmn-panel specs to renderPanel", () => {
    const renderPanel = vi.fn(() => <div>PANEL</div>);
    const raw = "id: p1\ntype: line\nmetrics: [loss]\n";
    render(<Markdown source={"```vmn-panel\n" + raw + "```"} renderPanel={renderPanel} />);
    expect(screen.getByText("PANEL")).toBeInTheDocument();
    expect(renderPanel).toHaveBeenCalledWith({ id: "p1", type: "line", metrics: ["loss"] }, raw);
  });

  it("renders a placeholder panel by default", () => {
    render(<Markdown source={"```vmn-panel\nid: p1\ntype: line\n```"} />);
    expect(screen.getByText(/p1/)).toBeInTheDocument();
    expect(screen.getByText(/line/)).toBeInTheDocument();
  });

  it("shows an error box for invalid YAML", () => {
    const renderPanel = vi.fn();
    render(<Markdown source={"```vmn-panel\nid: [unclosed\n```"} renderPanel={renderPanel} />);
    expect(renderPanel).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/invalid panel/i);
  });

  it("supports GFM tables", () => {
    const { container } = render(<Markdown source={"| a | b |\n|---|---|\n| 1 | 2 |"} />);
    expect(container.querySelector("table")).not.toBeNull();
  });

  it("anchors setext headings and keeps later slugs aligned", () => {
    const { container } = render(<Markdown source={"Intro\n=====\n\n## Next\n\nSub\n---\n\n# Last"} />);
    expect(container.querySelector("h1#intro")).not.toBeNull();
    expect(container.querySelector("h2#next")).not.toBeNull();
    expect(container.querySelector("h2#sub")).not.toBeNull();
    expect(container.querySelector("h1#last")).not.toBeNull();
    expect(screen.getByRole("navigation", { name: "Table of contents" })).toBeInTheDocument();
  });

  it("keeps in-page anchor links in the same tab", () => {
    render(<Markdown source="[jump](#intro)" />);
    expect(screen.getByRole("link", { name: "jump" })).not.toHaveAttribute("target");
  });
});

describe("Markdown rendering", () => {
  it("renders inline formatting, lists, quotes, code, rules and breaks", () => {
    const src = "**b** *i* ~~s~~ `c`  \nnext\n\n- one\n  1. two\n\n> q\n\n```js\nx<y\n```\n\n---";
    const { container } = render(<Markdown source={src} />);
    for (const sel of ["strong", "em", "del", "p code", "br", "ul > li ol > li", "blockquote p", "pre code.language-js", "hr"]) {
      expect(container.querySelector(sel), sel).not.toBeNull();
    }
    expect(container.querySelector("pre code")).toHaveTextContent("x<y");
  });

  it("renders unsafe link schemes as plain text", () => {
    const { container } = render(<Markdown source={"[bad](javascript:alert(1)) [ok](./rel) [m](mailto:a@b.c)"} />);
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(container).toHaveTextContent("bad");
    expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute("href", "./rel");
    expect(screen.getByRole("link", { name: "m" })).toHaveAttribute("href", "mailto:a@b.c");
  });

  it("accepts JSON vmn-panel specs", () => {
    const renderPanel = vi.fn(() => <div>PANEL</div>);
    render(<Markdown source={'```vmn-panel\n{"id": "p1", "keys": ["a"]}\n```'} renderPanel={renderPanel} />);
    expect(renderPanel).toHaveBeenCalledWith({ id: "p1", keys: ["a"] }, '{"id": "p1", "keys": ["a"]}\n');
  });

  it("aligns table cells", () => {
    const { container } = render(<Markdown source={"| a | b |\n|:-:|--:|\n| 1 | 2 |"} />);
    expect(container.querySelector("th")).toHaveStyle({ textAlign: "center" });
    expect(container.querySelectorAll("tbody td")[1]).toHaveStyle({ textAlign: "right" });
  });
});
