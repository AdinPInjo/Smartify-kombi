// CHANGELOG.md, built into the dashboard: the changelog works offline in the van
// and on the remote dashboard alike.
import raw from "../../../CHANGELOG.md?raw";

export interface ChangelogEntry {
  version: string;
  date: string | null;
  notes: string;
}

const HEADING = /^## (\d+\.\d+\.\d+)(?:\s*[-–—]\s*(\d{4}-\d{2}-\d{2}))?\s*$/;

export function parseChangelog(text: string): ChangelogEntry[] {
  const entries: ChangelogEntry[] = [];
  let current: { version: string; date: string | null; lines: string[] } | null = null;
  const done = () => current && entries.push({ version: current.version, date: current.date, notes: current.lines.join("\n").trim() });
  for (const line of text.split("\n")) {
    const match = HEADING.exec(line);
    if (match) {
      done();
      current = { version: match[1], date: match[2] ?? null, lines: [] };
    } else if (line.startsWith("## ")) {
      done();
      current = null;
    } else if (current) {
      current.lines.push(line);
    }
  }
  done();
  return entries;
}

export const CHANGELOG = parseChangelog(raw);
