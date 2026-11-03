import { useHealth } from "@/api/hooks";
import { Notes } from "@/components/Notes";
import { PageHeader } from "@/components/PageHeader";
import { CHANGELOG } from "@/lib/changelog";

function date(value: string | null): string {
  if (!value) return "";
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

export function Changelog() {
  const health = useHealth();
  const installed = health.data?.version ?? __APP_VERSION__;
  return (
    <main className="page" style={{ maxWidth: 760 }}>
      <PageHeader kicker="Smartify · Kombi" title="What's new" sub={`Installed: ${installed}`} />
      {CHANGELOG.map((entry) => (
        <section key={entry.version} className={`card ${entry.version === installed ? "highlight" : ""}`}>
          <div className="row-between">
            <h2 className="page-title" style={{ fontSize: 22, margin: 0 }}>
              {entry.version}
            </h2>
            <span className="row" style={{ gap: 8 }}>
              {entry.version === installed && <span className="chip">installed</span>}
              <span className="tiny faint">{date(entry.date)}</span>
            </span>
          </div>
          <Notes text={entry.notes} />
        </section>
      ))}
    </main>
  );
}
