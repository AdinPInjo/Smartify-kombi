import { Settings } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { RemoteBanner } from "./RemoteBanner";

export function PageHeader({ kicker, title, sub, right }: { kicker?: string; title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="stack" style={{ gap: 4, minWidth: 0 }}>
        {kicker && <div className="label">{kicker}</div>}
        <h1 className="page-title">{title}</h1>
        {sub && <div className="muted small">{sub}</div>}
        <RemoteBanner />
      </div>
      <div className="row">
        {right}
        <Link to="/settings" className="btn ghost phone-only" aria-label="Settings" style={{ minWidth: 44, padding: 0 }}>
          <Settings size={22} aria-hidden="true" />
        </Link>
      </div>
    </header>
  );
}
