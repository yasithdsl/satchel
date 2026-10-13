import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseMarkdown } from "../lib/markdown.ts";

describe("parseMarkdown", () => {
  it("parses paragraphs split by blank lines", () => {
    assert.deepEqual(parseMarkdown("one\n\n\n\ntwo"), [
      { kind: "paragraph", text: "one" },
      { kind: "paragraph", text: "two" },
    ]);
  });

  it("joins wrapped lines inside a paragraph", () => {
    assert.deepEqual(parseMarkdown("hello\nworld"), [
      { kind: "paragraph", text: "hello world" },
    ]);
  });

  it("starts a bullet list without a preceding blank line", () => {
    assert.deepEqual(
      parseMarkdown("The other two:\n- **Nimbus** earbuds\n- **Pulse** band"),
      [
        { kind: "paragraph", text: "The other two:" },
        {
          kind: "list",
          ordered: false,
          items: ["**Nimbus** earbuds", "**Pulse** band"],
        },
      ],
    );
  });

  it("accepts * as a bullet marker", () => {
    assert.deepEqual(parseMarkdown("* first\n* second"), [
      { kind: "list", ordered: false, items: ["first", "second"] },
    ]);
  });

  it("parses numbered lists", () => {
    assert.deepEqual(
      parseMarkdown("Steps:\n1. ask\n2. approve\n3. buy"),
      [
        { kind: "paragraph", text: "Steps:" },
        {
          kind: "list",
          ordered: true,
          items: ["ask", "approve", "buy"],
        },
      ],
    );
  });

  it("ends a list when a plain line follows", () => {
    assert.deepEqual(parseMarkdown("- a\n- b\ndone"), [
      { kind: "list", ordered: false, items: ["a", "b"] },
      { kind: "paragraph", text: "done" },
    ]);
  });

  it("splits mixed bullet and numbered lists", () => {
    assert.deepEqual(parseMarkdown("- a\n1. b"), [
      { kind: "list", ordered: false, items: ["a"] },
      { kind: "list", ordered: true, items: ["b"] },
    ]);
  });
});
