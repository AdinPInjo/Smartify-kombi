// Settings card: connect the van to its remote dashboard (on the van), or show
// the van connection and make a new connection code (on the remote dashboard).
import { CheckCircle2, Globe } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import { ErrorNote, useErrorToast, useToast } from "./ui";
import { ago } from "@/lib/format";

interface CloudView {
  connected: boolean;
  source: "dashboard" | "env" | null;
  url: string | null;
  status: { last_ok_at: number | null; last_error: string | null; last_error_at: number | null; commands_applied: number } | null;
}

/** The address inside a connection code, to show before connecting. */
function codeHost(code: string): string | null {
  try {
    const payload = code.trim().replace(/^SMK1-/, "").replace(/-/g, "+").replace(/_/g, "/");
    const data = JSON.parse(atob(payload + "=".repeat((4 - (payload.length % 4)) % 4)));
    return typeof data.u === "string" ? data.u.replace(/^https?:\/\//, "") : null;
  } catch {
    return null;
  }
}

function useScrollHere(id: string) {
  const ref = useRef<HTMLElement>(null);
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === `#${id}`) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash, id]);
  return ref;
}

export function RemoteDashboardCard() {
  const { cloud } = useMode();
  return cloud ? <VanConnection /> : <ConnectVan />;
}

// --- on the van ----------------------------------------------------------------------

function ConnectVan() {
  const client = useQueryClient();
  const toast = useToast();
  const showError = useErrorToast();
  const location = useLocation();
  const navigate = useNavigate();
  const ref = useScrollHere("remote");
  const view = useQuery({ queryKey: ["cloud"], queryFn: () => api.get<CloudView>("/cloud"), refetchInterval: 10_000 });
  const fromLink = useMemo(() => new URLSearchParams(location.search).get("connect"), [location.search]);
  const [code, setCode] = useState(fromLink ?? "");
  useEffect(() => {
    if (fromLink) setCode(fromLink);
  }, [fromLink]);

  const connect = useMutation({
    mutationFn: (value: string) => api.post<CloudView>("/cloud", { code: value.trim() }),
    onSuccess: (data) => {
      client.setQueryData(["cloud"], data);
      setCode("");
      toast("Connected to the remote dashboard");
      if (fromLink) navigate({ pathname: location.pathname, hash: "remote" }, { replace: true });
    },
  });
  const disconnect = useMutation({
    mutationFn: () => api.delete<CloudView>("/cloud"),
    onSuccess: (data) => {
      client.setQueryData(["cloud"], data);
      toast("Disconnected");
    },
    onError: showError,
  });

  const v = view.data;
  const status = v?.status;
  const healthy = status?.last_ok_at && (!status.last_error_at || status.last_ok_at >= status.last_error_at);
  const host = codeHost(code);

  return (
    <section id="remote" ref={ref} className="card" style={{ scrollMarginTop: 16 }}>
      <div className="row-between">
        <h2 className="label row" style={{ margin: 0, gap: 8 }}>
          <Globe size={15} aria-hidden="true" /> Remote dashboard
        </h2>
        {v?.connected && (
          <span className="chip">
            <span className={`dot ${healthy ? "ok" : "warn"}`} />
            {healthy ? "connected" : "not reaching it"}
          </span>
        )}
      </div>

      {v?.connected ? (
        <>
          <div className="stack" style={{ gap: 4 }}>
            <a href={v.url ?? "#"} target="_blank" rel="noreferrer" style={{ overflowWrap: "anywhere" }}>
              {v.url?.replace(/^https?:\/\//, "")}
            </a>
            <span className="small muted">
              {status?.last_ok_at ? `Last sync ${ago(status.last_ok_at)}` : "Not synced yet"}
              {status?.commands_applied ? ` · ${status.commands_applied} remote changes applied` : ""}
            </span>
            {status?.last_error && !healthy && <span className="small c-alert">{status.last_error}</span>}
          </div>
          {v.source === "env" ? (
            <span className="tiny faint">Set in backend/.env. Paste a new code below to switch to a connection made here.</span>
          ) : (
            <button
              type="button"
              className="btn small ghost"
              style={{ alignSelf: "flex-start" }}
              disabled={disconnect.isPending}
              onClick={() => window.confirm("Disconnect from the remote dashboard? It keeps its data but gets no updates.") && disconnect.mutate()}
            >
              Disconnect
            </button>
          )}
        </>
      ) : (
        <p className="small muted" style={{ margin: 0 }}>
          See and switch your van from anywhere, through your own website. Install the remote dashboard on your web hosting
          (see the project's README, “Remote dashboard”), then paste the connection code it shows here.
        </p>
      )}

      {fromLink && host && !connect.isSuccess ? (
        <div className="notice stack" style={{ gap: 10 }}>
          <span>
            Connect this van to the remote dashboard at <strong>{host}</strong>?
          </span>
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn primary small" disabled={connect.isPending} onClick={() => connect.mutate(code)}>
              {connect.isPending ? "Connecting…" : "Connect"}
            </button>
            <button type="button" className="btn ghost small" onClick={() => navigate({ pathname: location.pathname }, { replace: true })}>
              Not now
            </button>
          </div>
        </div>
      ) : (
        <form
          className="stack"
          style={{ gap: 8 }}
          onSubmit={(e) => {
            e.preventDefault();
            connect.mutate(code);
          }}
        >
          <input
            className="input mono"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={v?.connected ? "New connection code (SMK1-…)" : "Connection code (SMK1-…)"}
            aria-label="Connection code"
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
          {code && host && <span className="tiny faint">Remote dashboard: {host}</span>}
          <button type="submit" className="btn small" style={{ alignSelf: "flex-start" }} disabled={!code.trim() || connect.isPending}>
            {connect.isPending ? "Connecting…" : "Connect"}
          </button>
        </form>
      )}
      <ErrorNote error={connect.error} />
      {connect.isSuccess && (
        <div className="notice ok row" style={{ gap: 8 }}>
          <CheckCircle2 size={18} aria-hidden="true" /> Connected. The van's data appears there within a minute.
        </div>
      )}
    </section>
  );
}

// --- on the remote dashboard ------------------------------------------------------------

interface VanLink {
  url: string;
  last_seen: number | null;
  online: boolean;
  version: string;
  van_version: string | null;
}

function VanConnection() {
  const ref = useScrollHere("remote");
  const view = useQuery({ queryKey: ["cloud", "connection"], queryFn: () => api.get<VanLink>("/cloud/connection"), refetchInterval: 10_000 });
  const [code, setCode] = useState<string | null>(null);
  const [van, setVan] = useState("smartify.local");
  const toast = useToast();
  const showError = useErrorToast();
  const newCode = useMutation({
    mutationFn: () => api.post<{ code: string }>("/cloud/connection-code"),
    onSuccess: (data) => setCode(data.code),
    onError: showError,
  });
  const v = view.data;
  const host = van.trim().replace(/^https?:\/\//, "").replace(/\/.*$/, "") || "smartify.local";

  return (
    <section id="remote" ref={ref} className="card" style={{ scrollMarginTop: 16 }}>
      <div className="row-between">
        <h2 className="label row" style={{ margin: 0, gap: 8 }}>
          <Globe size={15} aria-hidden="true" /> Van connection
        </h2>
        {v && (
          <span className="chip">
            <span className={`dot ${v.online ? "ok" : "bad"}`} />
            {v.online ? "van online" : "van offline"}
          </span>
        )}
      </div>
      <span className="small muted">
        {v?.last_seen ? `Last contact ${ago(v.last_seen)}` : "The van has not connected yet."}
        {v?.van_version ? ` · van ${v.van_version}, remote ${v.version}` : ""}
      </span>
      {code ? (
        <div className="stack" style={{ gap: 10 }}>
          <span className="small">New code made. The van reconnects once it gets it:</span>
          <div className="topic" style={{ fontSize: 13, textAlign: "left" }}>{code}</div>
          <div className="row wrap" style={{ gap: 8 }}>
            <button type="button" className="btn small" onClick={() => navigator.clipboard?.writeText(code).then(() => toast("Code copied"))}>
              Copy code
            </button>
            <input className="input" style={{ width: 170, minHeight: 36 }} value={van} onChange={(e) => setVan(e.target.value)} aria-label="Your van's address" />
            <a className="btn small primary" href={`http://${host}/settings?connect=${encodeURIComponent(code)}#remote`} target="_blank" rel="noreferrer">
              Connect my van
            </a>
          </div>
          <span className="tiny faint">“Connect my van” works while your phone is on the van's WiFi. Otherwise paste the code in the van's Settings.</span>
        </div>
      ) : (
        <button
          type="button"
          className="btn small"
          style={{ alignSelf: "flex-start" }}
          disabled={newCode.isPending}
          onClick={() =>
            window.confirm("Make a new connection code? The van disconnects until you give it the new code.") && newCode.mutate()
          }
        >
          New connection code
        </button>
      )}
    </section>
  );
}
