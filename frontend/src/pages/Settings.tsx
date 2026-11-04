import { Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import {
  useMe,
  useMode,
  useWifi,
  useWifiConnect,
  useWifiNetworks,
} from "@/api/hooks";
import type { WifiNetwork } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { RemoteDashboardCard } from "@/components/RemoteDashboardCard";
import { UpdatesCard } from "@/components/UpdatesCard";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Dialog, ErrorNote, Field, Segmented, useToast } from "@/components/ui";
import { SUPPORT_URL } from "@/lib/support";
import { useLook, type Theme } from "@/lib/look";

export function Settings() {
  const me = useMe();
  return (
    <main className="page">
      <PageHeader kicker="Settings" title="Settings" />
      {me.data?.default_credentials && (
        <div className="notice">You are using the default development password. Set your own under Account below.</div>
      )}
      <div className="grid">
        <div className="stack" style={{ gap: "var(--gap)" }}>
          <WifiCard />
          <RemoteDashboardCard />
        </div>
        <div className="stack" style={{ gap: "var(--gap)" }}>
          <LookCard />
          <AccountCard />
          <UpdatesCard />
          <Card label="More">
            <div className="list">
              <Link to="/?edit=1" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>Customize the overview</span>
                <span className="muted">›</span>
              </Link>
              <Link to="/changelog" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>What's new (changelog)</span>
                <span className="muted">›</span>
              </Link>
              <Link to="/system" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>System status & logs</span>
                <span className="muted">›</span>
              </Link>
              <a href={SUPPORT_URL} target="_blank" rel="noreferrer" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>Support the project ♥</span>
                <span className="muted">Ko-fi ↗</span>
              </a>
              <LogoutRow />
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}

// --- look ------------------------------------------------------------------------------------

function LookCard() {
  const { look, save } = useLook();
  return (
    <Card label="Look">
      <div className="stack" style={{ gap: 6 }}>
        <span className="small muted">Theme</span>
        <Segmented<Theme>
          label="Theme"
          value={look.theme}
          onChange={(theme) => save({ ...look, theme })}
          options={[
            { value: "dark", label: "Dark" },
            { value: "light", label: "Daylight" },
            { value: "auto", label: "Auto" },
          ]}
        />
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <span className="small muted">Card colors</span>
        <Segmented<"on" | "off">
          label="Card colors"
          value={look.colorful ? "on" : "off"}
          onChange={(value) => save({ ...look, colorful: value === "on" })}
          options={[
            { value: "on", label: "Colorful" },
            { value: "off", label: "Calm" },
          ]}
        />
      </div>
      <span className="tiny faint">
        Auto follows your phone's light or dark mode. Saved on this device, so the wall tablet can look different.
      </span>
    </Card>
  );
}

// --- account ---------------------------------------------------------------------------------

function AccountCard() {
  const { cloud } = useMode();
  const me = useMe();
  const client = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (cloud) {
    return (
      <Card label="Account">
        <OnlyOnVan what="Changing the van's login" />
      </Card>
    );
  }
  const reset = () => {
    setOpen(false);
    setCurrent("");
    setPassword("");
    setRepeat("");
    setError(null);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== repeat) return setError(new Error("The new passwords are not the same."));
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/password", {
        current_password: current,
        new_password: password,
        username: username.trim() || undefined,
      });
      await client.invalidateQueries({ queryKey: ["me"] });
      toast("Login changed. Other devices need to sign in again.");
      reset();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card label="Account">
      <div className="row-between">
        <span>
          Signed in as <strong>{me.data?.user ?? "…"}</strong>
        </span>
        {!open && (
          <button type="button" className="btn small" onClick={() => { setUsername(me.data?.user ?? ""); setOpen(true); }}>
            Change login
          </button>
        )}
      </div>
      {me.data?.login_source === "env" && !open && (
        <span className="tiny faint">Your password is still in backend/.env. Changing it here moves it to the dashboard, stored safely hashed.</span>
      )}
      {open && (
        <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
          <Field label="Current password">
            <input className="input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" required autoFocus />
          </Field>
          <Field label="Username">
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="off" required />
          </Field>
          <div className="grid-2">
            <Field label="New password" hint="At least 8 characters.">
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" minLength={8} required />
            </Field>
            <Field label="Repeat new password">
              <input className="input" type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" minLength={8} required />
            </Field>
          </div>
          <ErrorNote error={error} />
          <div className="row" style={{ gap: 8 }}>
            <button type="submit" className="btn primary small" disabled={busy}>
              {busy ? "Saving…" : "Save new login"}
            </button>
            <button type="button" className="btn ghost small" onClick={reset}>
              Cancel
            </button>
          </div>
          <span className="tiny faint">Your other phones and tablets will need to sign in again.</span>
        </form>
      )}
    </Card>
  );
}

function LogoutRow() {
  const navigate = useNavigate();
  const client = useQueryClient();
  return (
    <button
      type="button"
      className="row-between"
      style={{ minHeight: 44, background: "none", border: 0, padding: "12px 0", cursor: "pointer", width: "100%" }}
      onClick={async () => {
        await api.post("/auth/logout");
        client.clear();
        navigate("/login");
      }}
    >
      <span>Sign out</span>
      <span className="muted">›</span>
    </button>
  );
}

// --- WiFi --------------------------------------------------------------------------

function WifiCard() {
  const { cloud } = useMode();
  if (cloud) {
    return (
      <Card label="WiFi">
        <OnlyOnVan what="Changing the van's WiFi" />
      </Card>
    );
  }
  return <WifiControls />;
}

function WifiControls() {
  const wifi = useWifi();
  const [scan, setScan] = useState(false);
  const networks = useWifiNetworks(scan);
  const [joining, setJoining] = useState<WifiNetwork | null>(null);
  const status = wifi.data;

  return (
    <Card label="WiFi">
      <div className="row-between">
        <span className="row">
          <span className={`dot ${status?.connected ? "ok" : "bad"}`} />
          <span>
            {status?.connected ? <strong>{status.ssid ?? "Connected"}</strong> : "Not connected"}
            {status?.ip_address && <span className="small muted"> · {status.ip_address}</span>}
          </span>
        </span>
        <button type="button" className="btn small" onClick={() => (scan ? networks.refetch() : setScan(true))} disabled={networks.isFetching}>
          {networks.isFetching ? "Scanning…" : "Scan"}
        </button>
      </div>
      {status?.error && <span className="small c-accent">{status.error}</span>}
      <ErrorNote error={networks.error} />
      {networks.data && (
        <div className="list">
          {networks.data.map((network) => (
            <button
              key={network.ssid}
              type="button"
              className="row-between"
              onClick={() => !network.in_use && setJoining(network)}
              style={{ background: "none", border: 0, cursor: network.in_use ? "default" : "pointer", textAlign: "left", minHeight: 44 }}
            >
              <span>
                {network.ssid} {network.secured ? <Lock size={13} className="muted" aria-label="secured" /> : null}
              </span>
              <span className="small muted">{network.in_use ? "connected" : `${network.signal}%`}</span>
            </button>
          ))}
        </div>
      )}
      {joining && <JoinDialog network={joining} onClose={() => setJoining(null)} />}
    </Card>
  );
}

function JoinDialog({ network, onClose }: { network: WifiNetwork; onClose: () => void }) {
  const connect = useWifiConnect();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    connect.mutate(
      { ssid: network.ssid, password: network.secured ? password : undefined },
      {
        onSuccess: (status) => {
          toast(`Connected to ${status.ssid ?? network.ssid}`);
          onClose();
        },
      },
    );
  };
  return (
    <Dialog title={`Join ${network.ssid}`} onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <p className="small muted" style={{ margin: 0 }}>
          If your phone reaches the Pi over WiFi, the dashboard may disconnect for a moment while the Pi switches networks.
        </p>
        {network.secured && (
          <Field label="Password">
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
          </Field>
        )}
        <ErrorNote error={connect.error} />
        <button type="submit" className="btn primary" disabled={connect.isPending}>
          {connect.isPending ? "Connecting…" : "Connect"}
        </button>
      </form>
    </Dialog>
  );
}
