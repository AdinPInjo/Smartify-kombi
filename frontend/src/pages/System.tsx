import { useState } from "react";
import { useLogs, useSystem } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { Card, Num, Segmented, Skeleton } from "@/components/ui";
import { ago, bytes, clock, duration, fmt } from "@/lib/format";

const LEVELS = [
  { value: "INFO", label: "Info" },
  { value: "WARNING", label: "Warnings" },
  { value: "ERROR", label: "Errors" },
];

export function System() {
  const system = useSystem();
  const [level, setLevel] = useState("INFO");
  const logs = useLogs(level);
  const s = system.data;

  return (
    <main className="page">
      <PageHeader kicker="System" title="Raspberry Pi" sub={s ? `Smartify ${s.version} · ${s.hardware === "mock" ? "simulated hardware" : "real hardware"}` : undefined} />
      {system.isPending && <Skeleton height={140} />}
      {s && (
        <>
          <div className="grid-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
            <div className="tile">
              <span className="tiny muted">CPU temperature</span>
              <Num value={fmt(s.cpu_temperature_c, 0)} unit="°C" size="m" className={(s.cpu_temperature_c ?? 0) > 75 ? "c-danger" : ""} />
            </div>
            <div className="tile">
              <span className="tiny muted">Uptime</span>
              <Num value={duration(s.uptime_seconds)} size="m" />
            </div>
            <div className="tile">
              <span className="tiny muted">Free disk</span>
              <Num value={bytes(s.disk_free_bytes)} size="m" />
              <span className="tiny muted">of {bytes(s.disk_total_bytes)}</span>
            </div>
            <div className="tile">
              <span className="tiny muted">Database</span>
              <Num value={bytes(s.database_bytes)} size="m" />
            </div>
          </div>
          <Card label="Background tasks">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Task</th>
                    <th>Last run</th>
                    <th>Last error</th>
                  </tr>
                </thead>
                <tbody>
                  {s.workers.map((w) => (
                    <tr key={w.name}>
                      <td>
                        <span className="row">
                          <span className={`dot ${!w.running ? "bad" : w.last_error && (w.last_error_at ?? 0) > (w.last_run_at ?? 0) - w.interval_seconds * 2 ? "warn" : "ok"}`} />
                          {w.name}
                        </span>
                      </td>
                      <td className="small muted">{ago(w.last_run_at)}</td>
                      <td className="small">{w.last_error ? `${w.last_error} (${ago(w.last_error_at)})` : <span className="faint">–</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
      <Card label="Log" action={<div style={{ width: 260 }}><Segmented label="Log level" options={LEVELS} value={level} onChange={setLevel} /></div>}>
        <div className="mono tiny" style={{ maxHeight: 420, overflowY: "auto", display: "flex", flexDirection: "column-reverse", gap: 4 }}>
          {[...(logs.data ?? [])].reverse().map((entry) => (
            <div key={entry.id} className={entry.level === "ERROR" ? "c-danger" : entry.level === "WARNING" ? "c-accent" : ""}>
              <span className="faint">{clock(entry.time)}</span> {entry.message}
            </div>
          ))}
          {logs.data?.length === 0 && <span className="muted">Nothing logged at this level.</span>}
        </div>
      </Card>
    </main>
  );
}
