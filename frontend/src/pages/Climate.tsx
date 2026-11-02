import { useState } from "react";
import { Link } from "react-router-dom";
import { useClimate, useClimateHistory, useWater, useWaterHistory, useWeather } from "@/api/hooks";
import type { ClimateSnapshot } from "@/api/types";
import { LineChart, Tank } from "@/components/instruments";
import { PageHeader } from "@/components/PageHeader";
import { Card, Num, Segmented, Skeleton } from "@/components/ui";
import { ago, fmt, weatherText } from "@/lib/format";

const RANGES = [
  { value: "6", label: "6 h" },
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
];

export function Climate() {
  const climate = useClimate();
  const weather = useWeather();
  const [hours, setHours] = useState("24");

  return (
    <main className="page">
      <PageHeader kicker="Climate" title="Temperature & water" />
      {climate.isPending && <Skeleton height={200} />}
      <div className="grid">
        {climate.data?.map((sensor) => <SensorCard key={sensor.sensor} sensor={sensor} hours={Number(hours)} />)}
      </div>
      <div style={{ maxWidth: 260 }}>
        <Segmented label="Time range" options={RANGES} value={hours} onChange={setHours} />
      </div>

      <WaterSection hours={Number(hours)} />

      <Card label="Outside weather">
        {!weather.data?.available ? (
          <p className="muted small" style={{ margin: 0 }}>{weather.data?.error ?? "Needs a GPS position and internet."}</p>
        ) : (
          <>
            <div className="row" style={{ gap: 18, flexWrap: "wrap" }}>
              <Num value={`${fmt(weather.data.temperature_c, 0)}°`} size="xl" />
              <div className="stack" style={{ gap: 2 }}>
                <span>{weatherText(weather.data.weather_code)}</span>
                <span className="small muted">
                  {fmt(weather.data.humidity, 0)}% · wind {fmt(weather.data.wind_kmh, 0)} km/h · updated {ago(weather.data.updated_at)}
                </span>
              </div>
            </div>
            <div className="grid-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))" }}>
              {weather.data.forecast?.map((day) => (
                <div className="tile" key={day.date}>
                  <span className="tiny muted">
                    {new Date(`${day.date}T12:00:00`).toLocaleDateString([], { weekday: "short" })}
                  </span>
                  <Num value={`${Math.round(day.temperature_max)}° / ${Math.round(day.temperature_min)}°`} size="s" />
                  <span className="tiny muted">
                    {weatherText(day.weather_code)}
                    {day.precipitation_mm > 0 ? ` · ${fmt(day.precipitation_mm, 1)} mm` : ""}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </Card>
    </main>
  );
}

function SensorCard({ sensor, hours }: { sensor: ClimateSnapshot; hours: number }) {
  const history = useClimateHistory(sensor.sensor, hours);
  const points = history.data ?? [];
  const times = points.map((p) => p.created_at);
  return (
    <Card label={sensor.sensor}>
      <div className="row-between" style={{ alignItems: "flex-end" }}>
        <Num value={fmt(sensor.temperature_c)} unit="°C" size="xl" />
        <div className="stack" style={{ alignItems: "flex-end", gap: 2 }}>
          <Num value={fmt(sensor.humidity, 0)} unit="%" size="m" />
          <span className="tiny muted">humidity</span>
        </div>
      </div>
      <span className={`small ${sensor.status === "ready" ? "muted" : "c-accent"}`}>
        {sensor.status === "ready"
          ? `Average of ${sensor.sample_count} readings · ${ago(sensor.last_good_at)}`
          : sensor.status === "warming_up"
            ? "Warming up, collecting first readings…"
            : `Not responding since ${ago(sensor.last_good_at)}${sensor.last_error ? ` (${sensor.last_error})` : ""}`}
      </span>
      <LineChart
        label={`${sensor.sensor} temperature`}
        unit="°C"
        times={times}
        series={[{ label: "Temperature", values: points.map((p) => p.temperature_c), color: "var(--accent)", fill: true }]}
      />
      <LineChart
        label={`${sensor.sensor} humidity`}
        unit="%"
        height={60}
        times={times}
        min={0}
        max={100}
        series={[{ label: "Humidity", values: points.map((p) => p.humidity), color: "var(--water)", dashed: true }]}
      />
    </Card>
  );
}

function WaterSection({ hours }: { hours: number }) {
  const water = useWater();
  const history = useWaterHistory(hours);
  const points = history.data ?? [];
  const level = water.data?.level_percent ?? null;
  return (
    <section id="water" className="card">
      <div className="row-between">
        <h2 className="label" style={{ margin: 0 }}>Fresh water</h2>
        <Link to="/settings#water" className="small">Calibrate ›</Link>
      </div>
      <div className="row" style={{ gap: 18, alignItems: "flex-end" }}>
        <Tank percent={level} height={140} width={56} />
        <div className="stack" style={{ gap: 4 }}>
          <Num value={level ?? "–"} unit="%" size="xl" />
          <span className={`small ${water.data?.ok ? "muted" : "c-accent"}`}>
            {water.data?.ok ? `Updated ${ago(water.data.updated_at)}` : (water.data?.error ?? "No reading yet")}
          </span>
        </div>
      </div>
      <LineChart
        label="Water level"
        unit="%"
        times={points.map((p) => p.created_at)}
        min={0}
        max={100}
        series={[{ label: "Level", values: points.map((p) => p.level_percent), color: "var(--water)", fill: true }]}
      />
    </section>
  );
}
