import { Lock } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import {
  useCalibrateWater,
  useMe,
  useMode,
  useUpdateWaterSettings,
  useWater,
  useWaterSettings,
  useWifi,
  useWifiConnect,
  useWifiNetworks,
} from "@/api/hooks";
import type { WifiNetwork } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Dialog, ErrorNote, Field, Segmented, useErrorToast, useToast } from "@/components/ui";
import { fmt } from "@/lib/format";
import { OVERVIEW_CARDS, useOverviewLayout } from "@/lib/overviewLayout";

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
          <OverviewCardSettings />
        </div>
        <div className="stack" style={{ gap: "var(--gap)" }}>
          <AccountCard />
          <WaterCalibration />
          <Card label="More">
            <div className="list">
              <Link to="/notifications" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>Notifications & alerts</span>
                <span className="muted">›</span>
              </Link>
              <Link to="/energy/devices" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>Victron devices</span>
                <span className="muted">›</span>
              </Link>
              <Link to="/system" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>System status & logs</span>
                <span className="muted">›</span>
              </Link>
              <Link to="/panel" className="row-between" style={{ minHeight: 44, color: "inherit" }}>
                <span>Open tablet panel</span>
                <span className="muted">›</span>
              </Link>
              <LogoutRow />
            </div>
          </Card>
        </div>
      </div>
    </main>
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

// --- water calibration ------------------------------------------------------------------

function WaterCalibration() {
  const { cloud } = useMode();
  const settings = useWaterSettings();
  const water = useWater();
  const calibrate = useCalibrateWater();
  const update = useUpdateWaterSettings();
  const showError = useErrorToast();
  const toast = useToast();
  const s = settings.data;
  const [divider, setDivider] = useState({ top: "", bottom: "" });
  useEffect(() => {
    if (s) setDivider({ top: String(s.divider_r_top), bottom: String(s.divider_r_bottom) });
  }, [s?.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const mark = (point: "empty" | "full") => {
    if (!window.confirm(`Is the tank really ${point} right now? The current reading becomes the ${point} point.`)) return;
    calibrate.mutate(point, { onSuccess: () => toast(`${point === "full" ? "Full" : "Empty"} point saved`), onError: showError });
  };

  return (
    <section id="water" className="card">
      <h2 className="label" style={{ margin: 0 }}>Water level calibration</h2>
      <div className="row" style={{ gap: 18, flexWrap: "wrap" }}>
        <span>
          Now <strong>{water.data?.level_percent ?? "–"}%</strong>
        </span>
        <span className="small muted">
          signal {fmt(water.data?.signal_voltage ?? null, 3)} V · battery {fmt(water.data?.battery_voltage ?? null, 2)} V · ratio{" "}
          {fmt(water.data?.ratio ?? null, 4)}
        </span>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        Fill the tank completely and press “Tank is full”. When it is empty, press “Tank is empty”. Both points are taken from
        the live reading.
      </p>
      {cloud ? (
        <OnlyOnVan what="Calibrating from the live reading" />
      ) : (
      <div className="grid-2">
        <button type="button" className="btn" onClick={() => mark("full")} disabled={calibrate.isPending}>
          Tank is full
        </button>
        <button type="button" className="btn" onClick={() => mark("empty")} disabled={calibrate.isPending}>
          Tank is empty
        </button>
      </div>
      )}
      {s && (
        <details>
          <summary className="small muted" style={{ cursor: "pointer", minHeight: 32 }}>Advanced</summary>
          <div className="stack" style={{ gap: 14, marginTop: 10 }}>
            <Field label="Method" hint="Ratio compensates the changing battery voltage. Use it unless your sensor has a regulated supply.">
              <Segmented
                label="Method"
                value={s.method}
                onChange={(method) => update.mutate({ method }, { onError: showError })}
                options={[
                  { value: "ratio", label: "Ratio (signal ÷ battery)" },
                  { value: "voltage", label: "Voltage only" },
                ]}
              />
            </Field>
            <div className="small muted">
              Full: {fmt(s.full_ratio, 4)} ({fmt(s.full_voltage, 3)} V) · Empty: {fmt(s.empty_ratio, 4)} ({fmt(s.empty_voltage, 3)} V) · ADC A
              {s.signal_channel} signal, A{s.supply_channel} supply
            </div>
            <form
              className="grid-2"
              onSubmit={(e) => {
                e.preventDefault();
                update.mutate(
                  { divider_r_top: Number(divider.top), divider_r_bottom: Number(divider.bottom) },
                  { onSuccess: () => toast("Divider saved"), onError: showError },
                );
              }}
            >
              <Field label="Divider top (Ω)">
                <input className="input" type="number" min={1} value={divider.top} onChange={(e) => setDivider({ ...divider, top: e.target.value })} />
              </Field>
              <Field label="Divider bottom (Ω)">
                <input className="input" type="number" min={1} value={divider.bottom} onChange={(e) => setDivider({ ...divider, bottom: e.target.value })} />
              </Field>
              <button type="submit" className="btn small" style={{ gridColumn: "1 / -1" }}>
                Save divider (fixes the battery voltage reading)
              </button>
            </form>
          </div>
        </details>
      )}
    </section>
  );
}

// --- overview layout --------------------------------------------------------------------

function OverviewCardSettings() {
  const { layout, save, reset } = useOverviewLayout();
  const move = (index: number, delta: number) => {
    const order = [...layout.order];
    const [item] = order.splice(index, 1);
    order.splice(index + delta, 0, item);
    save({ ...layout, order });
  };
  const toggle = (id: (typeof layout.order)[number]) =>
    save({ ...layout, hidden: layout.hidden.includes(id) ? layout.hidden.filter((h) => h !== id) : [...layout.hidden, id] });

  return (
    <section id="overview" className="card">
      <div className="row-between">
        <h2 className="label" style={{ margin: 0 }}>Overview cards</h2>
        <button type="button" className="btn ghost small" onClick={reset}>
          Reset
        </button>
      </div>
      <span className="small muted">Saved on this device, so the phone and the tablet can differ.</span>
      <div className="list">
        {layout.order.map((id, index) => {
          const label = OVERVIEW_CARDS.find((c) => c.id === id)?.label ?? id;
          const shown = !layout.hidden.includes(id);
          return (
            <div key={id} className="row-between">
              <label className="row" style={{ cursor: "pointer", minHeight: 44 }}>
                <input type="checkbox" checked={shown} onChange={() => toggle(id)} style={{ width: 22, height: 22, accentColor: "var(--accent)" }} />
                <span className={shown ? "" : "muted"}>{label}</span>
              </label>
              <span className="row" style={{ gap: 4 }}>
                <button type="button" className="btn small" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`Move ${label} up`}>
                  ↑
                </button>
                <button
                  type="button"
                  className="btn small"
                  onClick={() => move(index, 1)}
                  disabled={index === layout.order.length - 1}
                  aria-label={`Move ${label} down`}
                >
                  ↓
                </button>
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
