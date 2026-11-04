// Climate: is the van comfortable, and is the heater doing its job?
// Inside now (with a condensation hint), the heater, all temperatures in one
// chart, the sensors at a glance, and the weather where the van is.

import { Droplets, Wind } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useClimate, useWeather } from "@/api/hooks";
import type { ClimatePoint, ClimateSnapshot } from "@/api/types";
import { HeaterCards, useHeaters } from "@/components/Heater";
import { LineChart } from "@/components/instruments";
import { PageHeader } from "@/components/PageHeader";
import { Card, Num, Segmented, Skeleton } from "@/components/ui";
import { WeatherCard } from "@/components/WeatherCard";
import { ago, fmt } from "@/lib/format";

const RANGES = [
  { value: "6", label: "6 h" },
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
];

// One color per sensor line, in order.
const COLORS = ["var(--accent)", "var(--tone-weather)", "var(--tone-scenes)", "var(--tone-switches)", "var(--tone-charging)", "var(--tone-heater)"];

const isOutside = (name: string) => /out|ext|aussen|vani/i.test(name);

/** Dew point (°C) with the Magnus formula: below it, moisture condenses on surfaces. */
function dewPoint(temperature: number, humidity: number): number {
  const a = 17.62;
  const b = 243.12;
  const gamma = Math.log(humidity / 100) + (a * temperature) / (b + temperature);
  return (b * gamma) / (a - gamma);
}

function condensationHint(inside: ClimateSnapshot | undefined, outsideC: number | null): string | null {
  if (!inside || inside.temperature_c == null || inside.humidity == null) return null;
  const dew = dewPoint(inside.temperature_c, inside.humidity);
  if (outsideC != null && outsideC <= dew + 2) {
    return `Condensation likely: the air inside turns to water on surfaces below ${fmt(dew, 0)} °C, and it's ${fmt(outsideC, 0)} °C outside. Open a roof vent a little.`;
  }
  if (inside.humidity >= 70) {
    return "Humid inside: airing out for a few minutes helps against damp and mould.";
  }
  return null;
}

export function Climate() {
  const climate = useClimate();
  const weather = useWeather();
  const sensors = climate.data ?? [];
  const inside = sensors.find((s) => !isOutside(s.sensor)) ?? sensors[0];
  const outsideSensor = sensors.find((s) => s !== inside && isOutside(s.sensor));
  const outsideC = outsideSensor?.temperature_c ?? (weather.data?.available ? (weather.data.temperature_c ?? null) : null);
  const hint = condensationHint(inside, outsideC);

  return (
    <main className="page">
      <PageHeader kicker="Climate" title="Climate" sub="How comfortable the van is, and the heater that keeps it so." />
      {climate.isPending && <Skeleton height={180} />}
      {climate.data && (
        <InsideNow inside={inside} outsideC={outsideC} outsideFrom={outsideSensor ? outsideSensor.sensor : "forecast"} hint={hint} />
      )}
      <Card label="Diesel heater" action={<Link to="/climate/heaters" className="small">Setup ›</Link>}>
        <HeaterCards />
      </Card>
      {sensors.length > 0 && <Temperatures sensors={sensors} />}
      <div className="grid">
        <WeatherCard tall />
        <SensorList sensors={sensors} />
      </div>
    </main>
  );
}

function InsideNow({
  inside,
  outsideC,
  outsideFrom,
  hint,
}: {
  inside: ClimateSnapshot | undefined;
  outsideC: number | null;
  outsideFrom: string;
  hint: string | null;
}) {
  const heaters = useHeaters();
  const heater = heaters.data?.heaters[0];
  const s = heater?.status;
  const heaterLine = !heater
    ? null
    : !heater.connected
      ? `${heater.name}: not connected`
      : s?.running
        ? `${heater.name}: ${s.phase_name.toLowerCase()}${s.mode === "temperature" && s.target_temperature != null ? ` to ${fmt(s.target_temperature, 0)} °C` : s?.level ? ` at level ${s.level}` : ""}`
        : `${heater.name}: off`;

  if (!inside) {
    return (
      <Card label="Inside now">
        <p className="small muted" style={{ margin: 0 }}>
          No temperature sensor yet. <Link to="/sensors">Add one in the Sensors tab ›</Link>
        </p>
      </Card>
    );
  }
  return (
    <section className="card climate-hero">
      <div className="row-between" style={{ alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
        <div className="stack" style={{ gap: 4 }}>
          <span className="label">Inside now{/^(inside|cabin|innen|unutra)$/i.test(inside.sensor) ? "" : ` · ${inside.sensor}`}</span>
          <div className="row" style={{ alignItems: "flex-start", gap: 2 }}>
            <span className="num num-xxl">{fmt(inside.temperature_c)}</span>
            <span className="num c-accent" style={{ fontSize: 34, fontWeight: 500 }}>°C</span>
          </div>
          {heaterLine && <span className="small">{heaterLine}</span>}
        </div>
        <div className="climate-facts">
          {inside.humidity != null && (
            <div className="stack" style={{ gap: 0 }}>
              <span className="tiny muted row" style={{ gap: 4 }}><Droplets size={12} aria-hidden="true" /> humidity</span>
              <Num value={fmt(inside.humidity, 0)} unit="%" size="l" />
            </div>
          )}
          <div className="stack" style={{ gap: 0 }}>
            <span className="tiny muted row" style={{ gap: 4 }}>
              <Wind size={12} aria-hidden="true" /> {isOutside(outsideFrom) ? outsideFrom : `outside (${outsideFrom})`}
            </span>
            <Num value={fmt(outsideC, 0)} unit="°C" size="l" />
          </div>
        </div>
      </div>
      {inside.status !== "ready" && (
        <span className="small c-accent">
          {inside.status === "warming_up" ? "The sensor is starting, first readings come in…" : `No reading since ${ago(inside.last_good_at)}.`}{" "}
          <Link to="/sensors">Diagnose ›</Link>
        </span>
      )}
      {hint && <div className="notice small">{hint}</div>}
    </section>
  );
}

function Temperatures({ sensors }: { sensors: ClimateSnapshot[] }) {
  const [hours, setHours] = useState("24");
  const histories = useQueries({
    queries: sensors.map((s) => ({
      queryKey: ["climate", s.sensor, Number(hours)],
      queryFn: () => api.get<{ points: ClimatePoint[] }>(`/climate/${s.sensor}/history?hours=${hours}`).then((r) => r.points),
      refetchInterval: 60_000,
    })),
  });
  // All sensors are stored together once a minute, so their timestamps line up.
  const times = [...new Set(histories.flatMap((h) => (h.data ?? []).map((p) => p.created_at)))].sort((a, b) => a - b);
  const byTime = histories.map((h) => new Map((h.data ?? []).map((p) => [p.created_at, p])));
  const temperature = sensors.map((s, i) => ({
    label: s.sensor,
    values: times.map((t) => byTime[i].get(t)?.temperature_c ?? null),
    color: COLORS[i % COLORS.length],
    fill: i === 0,
  }));
  const humid = sensors
    .map((s, i) => ({ s, i }))
    .filter(({ s }) => s.humidity != null)
    .map(({ s, i }) => ({
      label: s.sensor,
      values: times.map((t) => byTime[i].get(t)?.humidity ?? null),
      color: COLORS[i % COLORS.length],
      dashed: true,
    }));

  return (
    <Card
      label="Temperatures"
      action={
        <div style={{ width: 230 }}>
          <Segmented label="Time range" options={RANGES} value={hours} onChange={setHours} />
        </div>
      }
    >
      <div className="row wrap" style={{ gap: 12 }}>
        {temperature.map((series) => (
          <span key={series.label} className="legend-item small">
            <i style={{ background: series.color }} /> {series.label}
          </span>
        ))}
      </div>
      <LineChart label="Temperatures" unit="°C" height={180} times={times} series={temperature} />
      {humid.length > 0 && (
        <>
          <span className="tiny muted">Humidity</span>
          <LineChart label="Humidity" unit="%" height={70} min={0} max={100} times={times} series={humid} />
        </>
      )}
    </Card>
  );
}

function SensorList({ sensors }: { sensors: ClimateSnapshot[] }) {
  return (
    <Card label="Sensors" action={<Link to="/sensors" className="small">Manage ›</Link>}>
      {sensors.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>None yet.</p>
      ) : (
        <div className="list">
          {sensors.map((s, i) => (
            <div key={s.sensor} className="row-between" style={{ gap: 10 }}>
              <span className="row" style={{ gap: 10 }}>
                <span className="legend-swatch" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="stack" style={{ gap: 0 }}>
                  <strong>{s.sensor}</strong>
                  <span className="tiny muted">
                    {s.status === "ready" ? `updated ${ago(s.last_good_at)}` : s.status === "warming_up" ? "starting…" : "not responding"}
                  </span>
                </span>
              </span>
              <span className="row" style={{ gap: 12 }}>
                <Num value={fmt(s.temperature_c)} unit="°C" size="s" />
                {s.humidity != null && <Num value={fmt(s.humidity, 0)} unit="%" size="s" />}
                <span className={`dot ${s.status === "ready" ? "ok" : s.status === "warming_up" ? "warn" : "bad"}`} />
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
