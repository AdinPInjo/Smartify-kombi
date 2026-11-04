// Weather where the van is (from its GPS position): now, and the next days.

import { Cloud, CloudDrizzle, CloudFog, CloudLightning, CloudRain, CloudSnow, CloudSun, Sun, Wind, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { useWeather } from "@/api/hooks";
import { Card, Num } from "./ui";
import { ago, fmt, weatherText } from "@/lib/format";

export function weatherIcon(code: number | null | undefined): LucideIcon {
  if (code === null || code === undefined) return Cloud;
  if (code === 0) return Sun;
  if (code <= 2) return CloudSun;
  if (code === 3) return Cloud;
  if (code <= 48) return CloudFog;
  if (code <= 57) return CloudDrizzle;
  if (code <= 67) return CloudRain;
  if (code <= 77) return CloudSnow;
  if (code <= 82) return CloudRain;
  if (code <= 86) return CloudSnow;
  return CloudLightning;
}

function dayName(date: string, index: number): string {
  if (index === 0) return "Today";
  return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { weekday: "short" });
}

export function WeatherCard({ tall = false }: { tall?: boolean }) {
  const weather = useWeather();
  const w = weather.data;
  if (!w?.available) {
    return (
      <Card label="Weather">
        <p className="small muted" style={{ margin: 0 }}>
          {w?.error ?? "Waiting for the first GPS position…"}
        </p>
      </Card>
    );
  }
  const Icon = weatherIcon(w.weather_code);
  const days = (w.forecast ?? []).slice(0, tall ? 7 : 4);
  return (
    <Card label="Weather here" action={<Link to="/climate" className="small" aria-label="Climate details">›</Link>}>
      <div className="row-between" style={{ alignItems: "center" }}>
        <div className="stack" style={{ gap: 2 }}>
          <Num value={fmt(w.temperature_c ?? null, 0)} unit="°C" size="l" />
          <span className="small">{weatherText(w.weather_code)}</span>
        </div>
        <Icon size={tall ? 64 : 46} strokeWidth={1.5} aria-hidden="true" className="weather-icon" />
      </div>
      <div className="weather-days">
        {days.map((day, i) => {
          const DayIcon = weatherIcon(day.weather_code);
          return (
            <div key={day.date} className="weather-day">
              <span className="tiny muted">{dayName(day.date, i)}</span>
              <DayIcon size={20} aria-label={weatherText(day.weather_code)} />
              <span className="small">
                <strong>{Math.round(day.temperature_max)}°</strong>
                <span className="muted"> {Math.round(day.temperature_min)}°</span>
              </span>
              {day.precipitation_mm >= 0.5 && <span className="tiny" style={{ color: "var(--water)" }}>{fmt(day.precipitation_mm, 0)} mm</span>}
            </div>
          );
        })}
      </div>
      <span className="tiny faint row" style={{ gap: 6 }}>
        {w.wind_kmh != null && (
          <>
            <Wind size={12} aria-hidden="true" /> {fmt(w.wind_kmh, 0)} km/h ·
          </>
        )}
        at the van's GPS position · {ago(w.updated_at)}
      </span>
    </Card>
  );
}
