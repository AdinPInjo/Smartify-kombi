import type { ReactNode } from "react";

/** The changelog's small Markdown: "### Heading", "- item" (wrapped lines continue it), `code`. */
export function Notes({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: string[] = [];
  const inline = (line: string) =>
    line.split(/(`[^`]+`)/).map((part, i) => (part.startsWith("`") && part.endsWith("`") ? <code key={i}>{part.slice(1, -1)}</code> : part));
  const flush = () => {
    if (items.length) {
      blocks.push(
        <ul key={blocks.length} className="notes-list">
          {items.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      items = [];
    }
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("### ")) {
      flush();
      blocks.push(
        <div key={blocks.length} className="label" style={{ marginTop: 6 }}>
          {line.slice(4)}
        </div>,
      );
    } else if (line.startsWith("- ")) {
      items.push(line.slice(2));
    } else if (items.length && raw.startsWith("  ")) {
      items[items.length - 1] += ` ${line}`;
    } else {
      flush();
      blocks.push(
        <p key={blocks.length} className="small" style={{ margin: 0 }}>
          {inline(line)}
        </p>,
      );
    }
  }
  flush();
  return <div className="stack small" style={{ gap: 4 }}>{blocks}</div>;
}
