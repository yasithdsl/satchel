export type MarkdownBlock =
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

const BULLET_RE = /^[-*]\s+(.+)$/;
const ORDERED_RE = /^\d+\.\s+(.+)$/;

export function parseMarkdown(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  let para: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushPara = () => {
    if (para.length) {
      blocks.push({ kind: "paragraph", text: para.join(" ") });
      para = [];
    }
  };
  const flushList = () => {
    if (list && list.items.length) {
      blocks.push({
        kind: "list",
        ordered: list.ordered,
        items: list.items,
      });
    }
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushPara();
      flushList();
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    const ordered = bullet ? null : ORDERED_RE.exec(line);
    if (bullet || ordered) {
      flushPara();
      const wantOrdered = ordered !== null;
      if (!list || list.ordered !== wantOrdered) {
        flushList();
        list = { ordered: wantOrdered, items: [] };
      }
      list.items.push((bullet ?? ordered)![1]);
      continue;
    }
    flushList();
    para.push(line);
  }
  flushPara();
  flushList();
  return blocks;
}
