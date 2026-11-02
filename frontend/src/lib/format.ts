export function fmt(value: number | null | undefined, digits = 1, fallback = "–"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Signed number with a real minus sign. */
export function signed(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  const text = Math.abs(value).toFixed(digits);
  return value < 0 ? `−${text}` : value > 0 ? `+${text}` : text;
}

export function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 48) return rest ? `${hours} h ${rest} min` : `${hours} h`;
  return `${Math.floor(hours / 24)} d ${hours % 24} h`;
}

export function ago(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return "never";
  const diff = Math.max(0, now - ts);
  if (diff < 10) return "just now";
  return `${duration(diff)} ago`;
}

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function dateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString([], {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function bytes(n: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let value = n;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(value < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

export function coords(lat: number, lon: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)} ${ns} · ${Math.abs(lon).toFixed(4)} ${ew}`;
}

/** "bulk", "no_alarm", "engine_shutdown" -> "Bulk", "No alarm", "Engine shutdown" */
export function humanize(value: string | null | undefined): string {
  if (!value) return "–";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Open-Meteo WMO weather codes, short form. */
export function weatherText(code: number | null | undefined): string {
  if (code === null || code === undefined) return "–";
  if (code === 0) return "clear";
  if (code <= 2) return "partly cloudy";
  if (code === 3) return "cloudy";
  if (code <= 48) return "fog";
  if (code <= 57) return "drizzle";
  if (code <= 67) return "rain";
  if (code <= 77) return "snow";
  if (code <= 82) return "showers";
  if (code <= 86) return "snow showers";
  return "thunderstorm";
}

export const METRIC_UNITS: Record<string, string> = {
  temperature: "°C",
  humidity: "%",
  battery_soc: "%",
  battery_voltage: "V",
  battery_current: "A",
  solar_power: "W",
};

export const METRIC_LABELS: Record<string, string> = {
  temperature: "Temperature",
  humidity: "Humidity",
  battery_soc: "Battery %",
  battery_voltage: "Battery voltage",
  battery_current: "Battery current",
  solar_power: "Solar power",
};

/** YYYY-MM-DD in local time (matches the Pi's daily distance rows). */
export function localDay(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
