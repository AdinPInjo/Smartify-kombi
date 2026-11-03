// Settings → Updates: what's new, install it, or go back to an earlier version.
// The same card on the van and on the remote dashboard (each updates itself).
import { CheckCircle2, Download, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import { Notes } from "./Notes";
import { ErrorNote, Segmented, useErrorToast, useToast } from "./ui";
import { ApiError } from "@/api/client";
import { ago } from "@/lib/format";

type Mode = "off" | "notify" | "auto";

interface Version {
  version: string;
  date: string | null;
  notes: string;
}

interface Status {
  state: "running" | "done" | "failed" | "rolled_back";
  target: string;
  from: string;
  by: string;
  step: string | null;
  message: string | null;
  started_at: number;
  finished_at: number | null;
}

interface UpdatesView {
  current: string;
  mode: Mode;
  checked_at: number | null;
  check_error: string | null;
  latest: string | null;
  update_available: boolean;
  versions: Version[];
  can_install: boolean;
  reason: string | null;
  status: Status | null;
  remote: { version: string; update_available: boolean } | null;
  auto_hours: [number, number];
  background?: boolean;
}

function key(version: string): number[] {
  return version.split(".").map(Number);
}

function newer(a: string, b: string): boolean {
  const [x, y] = [key(a), key(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
}

function date(value: string | null): string {
  if (!value) return "";
  return new Date(`${value}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function UpdatesCard() {
  const { cloud } = useMode();
  const client = useQueryClient();
  const toast = useToast();
  const showError = useErrorToast();
  // On the van, Smartify restarts during an update: keep asking until it's back.
  const [waitingFor, setWaitingFor] = useState<string | null>(null);
  // This page still runs the old dashboard after an update made from it.
  const [reloadNeeded, setReloadNeeded] = useState(false);

  const view = useQuery({
    queryKey: ["updates"],
    queryFn: () => api.get<UpdatesView>("/updates"),
    refetchInterval: (q) => (waitingFor || q.state.data?.status?.state === "running" ? 2000 : 60_000),
    retry: waitingFor ? 30 : 1,
  });
  const v = view.data;
  const status = v?.status;
  const running = status?.state === "running";
  const finished = Boolean(waitingFor && status && !running && status.target === waitingFor);
  useEffect(() => {
    if (!finished) return;
    setWaitingFor(null);
    if (status?.state === "done") setReloadNeeded(true);
  }, [finished, status?.state]);

  const setData = (data: UpdatesView) => client.setQueryData(["updates"], data);
  const mode = useMutation({
    mutationFn: (value: Mode) => api.patch<UpdatesView>("/updates/settings", { mode: value }),
    onSuccess: setData,
    onError: showError,
  });
  const check = useMutation({
    mutationFn: () => api.post<UpdatesView>("/updates/check"),
    onSuccess: (data) => {
      setData(data);
      toast(data.check_error ? `Check failed: ${data.check_error}` : data.update_available ? `Version ${data.latest} is available` : "You have the newest version");
    },
    onError: showError,
  });
  const install = useMutation({
    mutationFn: (version: string) => api.post<UpdatesView>("/updates/install", { version }),
    onMutate: (version) => setWaitingFor(cloud ? null : version),
    onSuccess: (data) => {
      setData(data);
      if (cloud && data.status?.state === "done") setReloadNeeded(true);
      if (cloud) void client.invalidateQueries({ queryKey: ["updates"] }); // ask the new version
    },
    onError: (error) => {
      setWaitingFor(null);
      showError(error);
    },
  });

  const start = (version: string) => {
    if (!v) return;
    const back = newer(v.current, version);
    const where = cloud ? "The remote dashboard" : "Smartify";
    const text = back
      ? `Go back to version ${version}? ${where} restarts with it. Your settings and data stay.`
      : `Update to version ${version}? ${where} restarts, which takes ${cloud ? "a few seconds" : "about a minute"}. If the new version doesn't work, it goes back by itself.`;
    if (window.confirm(text)) install.mutate(version);
  };

  if (!v) {
    return (
      <section id="updates" className="card">
        <h2 className="label">Updates</h2>
        {view.error instanceof ApiError && view.error.status === 404 ? (
          <span className="small muted">
            {cloud
              ? "This remote dashboard can't update itself yet: upload installer.php from the newest release once."
              : "Updates turn on after Smartify restarts. On the Pi: sudo systemctl restart smartify"}
          </span>
        ) : view.error ? (
          <ErrorNote error={view.error} />
        ) : (
          <span className="small muted">Loading…</span>
        )}
      </section>
    );
  }

  const latest = v.versions[0];
  const busy = running || install.isPending || waitingFor !== null;
  const recent = status && !running && status.finished_at && Date.now() / 1000 - status.finished_at < 7 * 86400;
  const autoHint = cloud
    ? v.background
      ? `Installs new versions at night (${v.auto_hours[0]}–${v.auto_hours[1]}, server time) and shows the result here.`
      : "This hosting can't install in the background, so you'll see new versions here and install them with one tap."
    : `Installs new versions at night (${v.auto_hours[0]}–${v.auto_hours[1]}) while the van is parked, and tells you on your phone.`;
  const hint: Record<Mode, string> = {
    off: "No automatic checks. You can still check by hand.",
    notify: cloud
      ? "Shows new versions here. The van's phone notification mentions them too."
      : "A phone notification when a new version is out. You choose when to install it.",
    auto: autoHint,
  };

  return (
    <section id="updates" className="card">
      <div className="row-between">
        <h2 className="label" style={{ margin: 0 }}>
          {cloud ? "Updates (remote dashboard)" : "Updates"}
        </h2>
        <span className="chip">
          <span className={`dot ${v.update_available ? "warn" : "ok"}`} />
          {v.update_available ? `${v.latest} available` : "up to date"}
        </span>
      </div>

      <div className="row-between small" style={{ gap: 8, flexWrap: "wrap" }}>
        <span>
          Installed: <strong>{v.current}</strong>
          <span className="muted"> · checked {ago(v.checked_at)}</span>
        </span>
        <button type="button" className="btn small ghost" disabled={check.isPending || busy} onClick={() => check.mutate()}>
          {check.isPending ? "Checking…" : "Check now"}
        </button>
      </div>
      {v.check_error &&
        (v.check_error.startsWith("no release") ? (
          <span className="tiny faint">No new releases published yet.</span>
        ) : (
          <span className="tiny c-alert">Last check: {v.check_error}</span>
        ))}

      <Segmented<Mode>
        label="Updates"
        value={v.mode}
        disabled={mode.isPending}
        onChange={(value) => mode.mutate(value)}
        options={[
          { value: "off", label: "Off" },
          { value: "notify", label: "Tell me" },
          { value: "auto", label: "Automatic" },
        ]}
      />
      <span className="tiny faint">{hint[v.mode]}</span>

      {(running || waitingFor) && (
        <div className="notice row" style={{ gap: 10 }} role="status">
          <Loader2 size={18} className="spin" aria-hidden="true" />
          <span>
            Updating to {status?.target ?? waitingFor}: {status?.step ?? "starting"}…
            {!cloud && <span className="tiny faint" style={{ display: "block" }}>The dashboard is offline for about a minute and comes back by itself.</span>}
          </span>
        </div>
      )}

      {recent && status && (
        <div className={`notice ${status.state === "done" ? "ok" : "error"} stack`} style={{ gap: 8 }}>
          <span className="row" style={{ gap: 8 }}>
            {status.state === "done" ? <CheckCircle2 size={18} aria-hidden="true" /> : <RotateCcw size={18} aria-hidden="true" />}
            {status.message}
          </span>
          {status.state === "done" && reloadNeeded && (
            <button type="button" className="btn small" style={{ alignSelf: "flex-start" }} onClick={() => window.location.reload()}>
              Reload the dashboard
            </button>
          )}
        </div>
      )}

      {!v.can_install && v.reason && <div className="notice small">{v.reason}</div>}

      {v.update_available && latest && !busy && (
        <div className="stack" style={{ gap: 10, borderTop: "1px solid var(--line)", paddingTop: 12 }}>
          <div className="row-between">
            <strong>What's new in {latest.version}</strong>
            <span className="tiny faint">{date(latest.date)}</span>
          </div>
          <Notes text={latest.notes} />
          <button
            type="button"
            className="btn primary"
            disabled={!v.can_install}
            onClick={() => start(latest.version)}
          >
            <Download size={18} aria-hidden="true" /> Update to {latest.version}
          </button>
        </div>
      )}

      {v.remote?.update_available && (
        <span className="small muted">
          Your remote dashboard runs {v.remote.version}. Update it there, in its Settings → Updates.
        </span>
      )}

      <Link to="/changelog" className="small">
        What's new: the full changelog ›
      </Link>

      {v.versions.length > 0 && (
        <details>
          <summary className="small" style={{ cursor: "pointer", minHeight: 32 }}>
            All versions and going back
          </summary>
          <div className="list" style={{ marginTop: 8 }}>
            {v.versions.map((entry) => (
              <div key={entry.version} className="stack" style={{ gap: 6 }}>
                <div className="row-between" style={{ gap: 8 }}>
                  <span>
                    <strong>{entry.version}</strong> <span className="tiny faint">{date(entry.date)}</span>
                  </span>
                  {entry.version === v.current ? (
                    <span className="chip">installed</span>
                  ) : (
                    <button
                      type="button"
                      className="btn small"
                      disabled={!v.can_install || busy}
                      onClick={() => start(entry.version)}
                    >
                      {newer(v.current, entry.version) ? "Go back" : "Install"}
                    </button>
                  )}
                </div>
                <details>
                  <summary className="tiny faint" style={{ cursor: "pointer" }}>
                    Changes
                  </summary>
                  <Notes text={entry.notes} />
                </details>
              </div>
            ))}
          </div>
          <p className="tiny faint" style={{ margin: "8px 0 0" }}>
            Going back keeps your settings and data. Versions before 0.4.0 aren't listed: they can't update themselves.
          </p>
        </details>
      )}
    </section>
  );
}
