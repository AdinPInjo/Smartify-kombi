// A live log readout: everything Smartify does, filterable. With debug mode on
// (Settings → Troubleshooting) it includes every sensor reading.

import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import type { LogEntry } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Segmented } from "@/components/ui";
import { useDebugMode } from "@/lib/debug";

const LEVELS = [
  { value: "DEBUG", label: "Everything" },
  { value: "INFO", label: "Normal" },
  { value: "WARNING", label: "Problems" },
];

export function Logs() {
  const { cloud } = useMode();
  const [params] = useSearchParams();
  const debug = useDebugMode();
  const [level, setLevel] = useState(debug.data?.enabled ? "DEBUG" : "INFO");
  const [filter, setFilter] = useState(params.get("filter") ?? "");
  const [paused, setPaused] = useState(false);
  // Debug mode on: show everything (once it's known, the user can still change it).
  const debugOn = debug.data?.enabled;
  useEffect(() => {
    if (debugOn) setLevel("DEBUG");
  }, [debugOn]);
  const logs = useQuery({
    queryKey: ["logs", "live", level],
    queryFn: () => api.get<{ logs: LogEntry[] }>(`/logs?limit=500&level=${level}`).then((r) => r.logs),
    refetchInterval: paused ? false : 2_000,
    enabled: !cloud,
  });
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = logs.data ?? [];
    return needle ? list.filter((e) => `${e.logger} ${e.message}`.toLowerCase().includes(needle)) : list;
  }, [logs.data, filter]);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!paused) bottom.current?.scrollIntoView({ block: "end" });
  }, [shown.length, paused]);

  return (
    <main className="page">
      <PageHeader
        kicker="Troubleshooting"
        title="Logs"
        sub={
          debug.data?.enabled
            ? `Debug mode is on until ${new Date((debug.data.until ?? 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}: every reading is listed.`
            : "Turn on debug mode in Settings to see every sensor reading here."
        }
        right={<Link to="/settings#troubleshooting" className="small">Debug mode ›</Link>}
      />
      {cloud ? (
        <Card><OnlyOnVan what="The log" /></Card>
      ) : (
        <Card>
          <div className="row wrap" style={{ gap: 10 }}>
            <div style={{ minWidth: 260 }}>
              <Segmented label="Show" options={LEVELS} value={level} onChange={setLevel} />
            </div>
            <input
              className="input grow"
              style={{ minWidth: 160 }}
              placeholder="Filter, e.g. fridge or heater"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              aria-label="Filter the log"
            />
            <button type="button" className="btn small" onClick={() => setPaused(!paused)}>
              {paused ? <Play size={16} aria-hidden="true" /> : <Pause size={16} aria-hidden="true" />} {paused ? "Resume" : "Pause"}
            </button>
          </div>
          <div className="log-view mono tiny" role="log" aria-live="off">
            {shown.map((entry) => (
              <div key={entry.id} className={`log-line ${entry.level.toLowerCase()}`}>
                <span className="faint">{new Date(entry.time * 1000).toLocaleTimeString()}</span>{" "}
                <span className="log-level">{entry.level}</span>{" "}
                <span className="muted">{entry.logger.replace("smartify.", "")}</span> {entry.message}
              </div>
            ))}
            {shown.length === 0 && <span className="muted">Nothing here{filter ? " for this filter" : " yet"}.</span>}
            <div ref={bottom} />
          </div>
        </Card>
      )}
    </main>
  );
}
