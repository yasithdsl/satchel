import type { ReactNode } from "react";

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
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim().length > 0);
  return (
    <div className="space-y-2">
      {paragraphs.map((para, pi) => {
        const lines = para.split("\n");
        const bullets = lines.filter((l) => l.trim().startsWith("- "));
        if (bullets.length === lines.length && bullets.length > 0) {
          return (
            <ul key={pi} className="list-disc space-y-1 pl-5">
              {lines.map((l, li) => (
                <li key={li}>
                  {renderInline(l.trim().slice(2), `${pi}-${li}`)}
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={pi}>{renderInline(para.replace(/\n/g, " "), `${pi}`)}</p>
        );
      })}
    </div>
  );
}
