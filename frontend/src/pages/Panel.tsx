// Always-on instrument panel for a tablet mounted in the van (open /panel).
// Landscape first; keeps the screen awake where the browser allows it.

import { Car, Expand, LayoutGrid, SunMedium, X, Zap } from "lucide-react";
import { useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  useClimate,
  useClimateHistory,
  useEnergy,
  useGps,
  useRelays,
  useSystem,
  useTrack,
  useWater,
  useWeather,
  useWifi,
} from "@/api/hooks";
import { batteryColor, LevelBar, LineChart, RingGauge, Topo } from "@/components/instruments";
import { DashGrid } from "@/components/DashGrid";
import { RelayControl } from "@/components/RelayControl";
import { SceneButtons } from "@/components/Scenes";
import { TrackMap } from "@/components/TrackMap";
import { Num } from "@/components/ui";
import { coords, duration, fmt, humanize, signed, weatherText } from "@/lib/format";
import { useDashLayout, type DashDefinition } from "@/lib/dashLayout";
import { useNow } from "@/lib/useNow";

type PanelCardId = "battery" | "cabin" | "switches" | "water" | "scenes" | "map";

// The tablet's own arrangement, separate from the Overview's.
const PANEL: DashDefinition<PanelCardId> = {
  key: "smartify.panel.v1",
  cards: [
    { id: "battery", label: "House battery", w: 2, h: 2 },
    { id: "cabin", label: "Cabin", w: 2, h: 1 },
    { id: "switches", label: "Switches", w: 2, h: 2 },
    { id: "water", label: "Fresh water", w: 2, h: 1 },
    { id: "scenes", label: "Scenes", w: 4, h: 1 },
    { id: "map", label: "Map", w: 2, h: 1 },
  ],
};
const LABELS = Object.fromEntries(PANEL.cards.map((c) => [c.id, c.label])) as Record<PanelCardId, string>;

function useWakeLock() {
  useEffect(() => {
    let lock: { release: () => Promise<void> } | null = null;
    const request = async () => {
      try {
        // Not available on every browser (needs HTTPS or localhost on most).
        lock = await (navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<typeof lock> } }).wakeLock?.request(
          "screen",
        ) ?? null;
      } catch {
        /* ignore: the tablet's own "stay awake" setting still works */
      }
    };
    request();
    const onVisible = () => document.visibilityState === "visible" && request();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      lock?.release().catch(() => {});
    };
  }, []);
}

export function Panel() {
  useWakeLock();
  const now = useNow(10_000);
  const weather = useWeather();
  const gps = useGps();
  const fix = gps.data?.fix ?? null;
  const navigate = useNavigate();
  const { layout, save, reset } = useDashLayout(PANEL);
  const [params, setParams] = useSearchParams();
  const editing = params.get("edit") === "1";
  const setEditing = (on: boolean) => setParams(on ? { edit: "1" } : {}, { replace: true });
  const exit = () => {
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
    navigate("/");
  };

  return (
    <div className="shell panel">
      <Topo />
      <header className="row-between" style={{ position: "relative" }}>
        <div className="row wrap" style={{ alignItems: "baseline", gap: 18 }}>
          <span className="label">Smartify · Kombi</span>
          <span className="muted">
            {editing
              ? "Drag cards by their handle, pick a width and height. Saved on this tablet."
              : `${weather.data?.available ? `${fmt(weather.data.temperature_c, 0)}° ${weatherText(weather.data.weather_code)}` : ""}${
                  fix?.altitude_m != null ? ` · ${Math.round(fix.altitude_m)} m` : ""
                }`}
          </span>
        </div>
        {editing ? (
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="btn ghost" onClick={() => window.confirm("Back to the standard panel layout?") && reset()}>
              Reset
            </button>
            <button type="button" className="btn primary" onClick={() => setEditing(false)}>
              Done
            </button>
          </div>
        ) : (
          <div className="row" style={{ gap: 6 }}>
            <span className="num" style={{ fontSize: 44, marginRight: 8 }}>
              {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
            <button type="button" className="btn ghost" aria-label="Arrange the panel" onClick={() => setEditing(true)}>
              <LayoutGrid size={20} aria-hidden="true" />
            </button>
            <button
              type="button"
              className="btn ghost"
              aria-label="Full screen"
              onClick={() => document.documentElement.requestFullscreen?.().catch(() => {})}
            >
              <Expand size={20} aria-hidden="true" />
            </button>
            <button type="button" className="btn" onClick={exit}>
              <X size={20} aria-hidden="true" /> Exit
            </button>
          </div>
        )}
      </header>

      <DashGrid
        className="panel-dash"
        layout={layout}
        save={save}
        editing={editing}
        labels={LABELS}
        render={(card) => <PanelCard id={card.id} />}
      />
      <StatusBar />
    </div>
  );
}

function PanelCard({ id }: { id: PanelCardId }) {
  switch (id) {
    case "battery":
      return <BatteryColumn />;
    case "cabin":
      return <CabinCard />;
    case "switches":
      return <Switches />;
    case "water":
      return <WaterBar />;
    case "scenes":
      return (
        <section className="card">
          <span className="label">Scenes</span>
          <SceneButtons large />
        </section>
      );
    case "map":
      return (
        <section className="card flush">
          <PanelMap />
        </section>
      );
  }
}

function BatteryColumn() {
  const energy = useEnergy();
  const water = useWater();
  const e = energy.data;
  const b = e?.battery;
  const soc = b?.soc ?? null;
  return (
    <section className="card" style={{ gap: 16 }}>
      <div className="row-between">
        <span className="label">House battery</span>
        <span className="small muted">{e?.available ? "Victron" : "ADC"}</span>
      </div>
      <div style={{ alignSelf: "center" }}>
        <RingGauge value={soc} size={250} stroke={18} color={batteryColor(soc)} label={`Battery ${soc ?? "unknown"} percent`}>
          <Num value={soc !== null ? Math.round(soc) : "–"} unit="%" size="xl" />
          <span className="small muted">
            {b?.remaining_mins ? `~${duration(b.remaining_mins * 60)} left` : (b?.current ?? 0) > 0 ? "charging" : ""}
          </span>
        </RingGauge>
      </div>
      <div className="grid-3 divider">
        <div className="stack" style={{ gap: 2 }}>
          <Num value={fmt(b?.voltage ?? water.data?.battery_voltage ?? null, 2)} size="m" />
          <span className="tiny muted">volts</span>
        </div>
        <div className="stack" style={{ gap: 2 }}>
          <Num value={signed(b?.current ?? null)} size="m" className={(b?.current ?? 0) < 0 ? "c-alert" : "c-ok"} />
          <span className="tiny muted">amps</span>
        </div>
        <div className="stack" style={{ gap: 2 }}>
          <Num value={signed(b?.power ?? null, 0)} size="m" />
          <span className="tiny muted">watts</span>
        </div>
      </div>
      {e?.available && (
        <div className="stack" style={{ marginTop: "auto" }}>
          {e.solar && (
            <SourceRow icon={<SunMedium size={18} color="var(--solar)" aria-hidden="true" />} name="Solar" active={(e.solar.power ?? 0) > 0}
              value={`${fmt(e.solar.power, 0)} W`} detail={`${fmt((e.solar.yield_today_wh ?? 0) / 1000, 1)} kWh`} />
          )}
          {e.dcdc && (
            <SourceRow icon={<Car size={18} color="var(--accent)" aria-hidden="true" />} name="Alternator"
              active={Boolean(e.dcdc.charge_state && e.dcdc.charge_state !== "off")}
              value={`${fmt(e.dcdc.output_current, 1)} A`} detail={humanize(e.dcdc.charge_state).toLowerCase()} />
          )}
          {e.inverter && (
            <SourceRow icon={<Zap size={18} aria-hidden="true" />} name="Inverter" active={(e.inverter.ac_out_power ?? 0) > 0}
              value={`${fmt(e.inverter.ac_out_power, 0)} W`} detail={humanize(e.inverter.state).toLowerCase()} />
          )}
        </div>
      )}
    </section>
  );
}

function SourceRow({ icon, name, value, detail, active }: { icon: React.ReactNode; name: string; value: string; detail: string; active: boolean }) {
  return (
    <div className={`tile ${active ? "highlight" : ""}`} style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
      <span className="row">{icon}{name}</span>
      <span className="num" style={{ fontSize: 22 }}>
        {value} <span className="muted" style={{ fontSize: 15, fontWeight: 500 }}>· {detail}</span>
      </span>
    </div>
  );
}

function CabinCard() {
  const climate = useClimate();
  const [inside, outside] = climate.data ?? [];
  const history = useClimateHistory(inside?.sensor, 24);
  const outsideHistory = useClimateHistory(outside?.sensor, 24);
  const points = history.data ?? [];
  return (
    <section className="card" style={{ flex: 1 }}>
      <span className="label">Cabin{inside ? ` · ${inside.sensor}` : ""}</span>
      <div className="row-between" style={{ alignItems: "flex-end", gap: 16 }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 2 }}>
          <span className="num" style={{ fontSize: "clamp(96px, 12vw, 168px)", lineHeight: 0.8, letterSpacing: "-0.02em" }}>
            {fmt(inside?.temperature_c ?? null)}
          </span>
          <span className="num c-accent" style={{ fontSize: 52, fontWeight: 500 }}>°C</span>
        </div>
        <div className="stack" style={{ gap: 14, paddingBottom: 6 }}>
          {outside && (
            <div className="stack" style={{ gap: 0 }}>
              <span className="small muted">{outside.sensor}</span>
              <Num value={`${fmt(outside.temperature_c)}°`} size="l" />
            </div>
          )}
          <div className="stack" style={{ gap: 0 }}>
            <span className="small muted">Humidity</span>
            <Num value={`${fmt(inside?.humidity ?? null, 0)}%`} size="l" />
          </div>
        </div>
      </div>
      <div style={{ marginTop: "auto" }}>
        <LineChart
          label="Temperatures over the last 24 hours"
          unit="°C"
          height={110}
          times={points.map((p) => p.created_at)}
          series={[
            { label: "Inside", values: points.map((p) => p.temperature_c), color: "var(--accent)", fill: true },
            ...(outsideHistory.data && outsideHistory.data.length === points.length
              ? [{ label: "Outside", values: outsideHistory.data.map((p) => p.temperature_c), color: "var(--faint)", dashed: true }]
              : []),
          ]}
        />
        <div className="row-between tiny muted"><span>−24 h</span><span>now</span></div>
      </div>
    </section>
  );
}

function WaterBar() {
  const water = useWater();
  return (
    <section className="card" style={{ flexDirection: "row", alignItems: "center", gap: 22 }}>
      <div className="stack" style={{ gap: 2, width: 150 }}>
        <span className="label">Fresh water</span>
        <Num value={water.data?.level_percent ?? "–"} unit="%" size="xl" />
      </div>
      <div className="stack grow" style={{ gap: 8 }}>
        <LevelBar percent={water.data?.level_percent ?? null} />
        <div className="row-between tiny muted"><span>empty</span><span>¼</span><span>½</span><span>¾</span><span>full</span></div>
      </div>
    </section>
  );
}

function Switches() {
  const relays = useRelays();
  return (
    <section className="card">
      <span className="label">Switches</span>
      {relays.data?.map((relay) => <RelayControl key={relay.id} relay={relay} large />)}
    </section>
  );
}

function PanelMap() {
  const gps = useGps();
  const track = useTrack(24);
  const fix = gps.data?.fix ?? null;
  return (
    <div className="stack" style={{ height: "100%", gap: 0 }}>
      <div style={{ flex: 1, minHeight: 120 }}>
        <TrackMap points={track.data ?? []} position={fix} height="100%" interactive={false} label="Map of the last 24 hours" />
      </div>
      <div className="row-between small" style={{ padding: "10px 16px" }}>
        <span className="mono">{fix ? coords(fix.lat, fix.lon) : "No GPS fix"}</span>
        <Link to="/map" className="small">Map ›</Link>
      </div>
    </div>
  );
}

function StatusBar() {
  const wifi = useWifi();
  const gps = useGps();
  const energy = useEnergy();
  const system = useSystem();
  const devices = energy.data?.devices ?? [];
  return (
    <footer className="row wrap mono tiny muted" style={{ gap: 28, letterSpacing: "0.06em", position: "relative" }}>
      <span className="row">
        <span className={`dot ${wifi.data?.connected ? "ok" : "bad"}`} style={{ width: 8, height: 8 }} />
        WIFI {wifi.data?.ssid?.toUpperCase() ?? "OFF"}
      </span>
      <span>GPS {gps.data?.status === "ok" ? `${gps.data.fix?.satellites ?? "–"} SATS` : (gps.data?.status ?? "–").toUpperCase().replace("_", " ")}</span>
      {devices.length > 0 && <span>VICTRON {devices.filter((d) => !d.stale).length}/{devices.length}</span>}
      <span style={{ marginLeft: "auto" }}>
        PI {fmt(system.data?.cpu_temperature_c ?? null, 0)} °C · UP {system.data ? duration(system.data.uptime_seconds).toUpperCase() : "–"}
      </span>
    </footer>
  );
}
