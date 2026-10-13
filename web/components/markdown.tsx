import type { ReactNode } from "react";
import { parseMarkdown } from "@/lib/markdown.ts";

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts
    .filter((p) => p.length > 0)
    .map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
      ) : (
        <span key={`${keyPrefix}-${i}`}>{part}</span>
      ),
    );
}

export function LightMarkdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  return (
    <div className="space-y-2">
      {blocks.map((block, bi) =>
        block.kind === "list" ? (
          block.ordered ? (
            <ol key={bi} className="list-decimal space-y-1 pl-5">
              {block.items.map((item, ii) => (
                <li key={ii}>{renderInline(item, `${bi}-${ii}`)}</li>
              ))}
            </ol>
          ) : (
            <ul key={bi} className="list-disc space-y-1 pl-5">
              {block.items.map((item, ii) => (
                <li key={ii}>{renderInline(item, `${bi}-${ii}`)}</li>
              ))}
            </ul>
          )
        ) : (
          <p key={bi}>{renderInline(block.text, `${bi}`)}</p>
        ),
      )}
    </div>
  );
}
