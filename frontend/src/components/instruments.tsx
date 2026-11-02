// Instrument-style gauges and charts, drawn as plain SVG (no chart library:
// keeps the bundle small for a tablet left on all day).

import { useId } from "react";

/** 270° arc gauge, like an analog instrument. */
export function RingGauge({
  value,
  max = 100,
  size = 120,
  stroke = 10,
  color = "var(--ok)",
  label,
  children,
}: {
  value: number | null;
  max?: number;
  size?: number;
  stroke?: number;
  color?: string;
  label: string;
  children?: React.ReactNode;
}) {
  const r = (size - stroke) / 2 - 2;
  const circumference = 2 * Math.PI * r;
  const arc = circumference * 0.75;
  const fraction = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  const c = size / 2;
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }}>
      <svg role="img" aria-label={label} width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={c}
          cy={c}
          r={r}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
          strokeDasharray={`${arc} ${circumference}`}
          transform={`rotate(135 ${c} ${c})`}
          strokeLinecap="round"
        />
        {value !== null && (
          <circle
            cx={c}
            cy={c}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeDasharray={`${Math.max(0.01, arc * fraction)} ${circumference}`}
            transform={`rotate(135 ${c} ${c})`}
            strokeLinecap="round"
            style={{ transition: "stroke-dasharray 600ms ease" }}
          />
        )}
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
        }}
      >
        {children}
      </div>
    </div>
  );
}

export function batteryColor(soc: number | null): string {
  if (soc === null) return "var(--faint)";
  if (soc < 20) return "var(--danger)";
  if (soc < 40) return "var(--accent)";
  return "var(--ok)";
}

/** Vertical tank with quarter marks. */
export function Tank({ percent, height = 120, width = 46 }: { percent: number | null; height?: number; width?: number }) {
  return (
    <div
      role="img"
      aria-label={percent === null ? "Water level unknown" : `Water level ${percent} percent`}
      style={{
        width,
        height,
        border: "2px solid var(--line-strong)",
        borderRadius: 10,
        position: "relative",
        overflow: "hidden",
        flex: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 0,
          height: `${percent ?? 0}%`,
          background: "var(--water)",
          transition: "height 600ms ease",
        }}
      />
      {[25, 50, 75].map((mark) => (
        <div
          key={mark}
          style={{ position: "absolute", left: 0, right: 0, top: `${mark}%`, borderTop: "1px dashed var(--ground)", opacity: 0.6 }}
        />
      ))}
    </div>
  );
}

/** Horizontal level bar (panel view). */
export function LevelBar({ percent, color = "var(--water)" }: { percent: number | null; color?: string }) {
  return (
    <div style={{ height: 28, borderRadius: 8, background: "var(--surface-2)", position: "relative", overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: "0 auto 0 0",
          width: `${percent ?? 0}%`,
          background: color,
          transition: "width 600ms ease",
        }}
      />
    </div>
  );
}

export interface Series {
  values: (number | null)[];
  color: string;
  dashed?: boolean;
  fill?: boolean;
  label: string;
}

/** Line chart for time series sharing one x axis (timestamps). */
export function LineChart({
  times,
  series,
  height = 120,
  band,
  min,
  max,
  label,
  unit = "",
}: {
  times: number[];
  series: Series[];
  height?: number;
  band?: { from: number; to: number; color: string };
  min?: number;
  max?: number;
  label: string;
  unit?: string;
}) {
  const gradientId = useId();
  const width = 600;
  const pad = 4;
  const all = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  if (times.length < 2 || all.length < 2) {
    return (
      <div className="muted small" style={{ height, display: "grid", placeItems: "center" }}>
        Not enough data yet
      </div>
    );
  }
  let lo = min ?? Math.min(...all, ...(band ? [band.from] : []));
  let hi = max ?? Math.max(...all, ...(band ? [band.to] : []));
  if (hi - lo < 1e-6) {
    lo -= 1;
    hi += 1;
  }
  const t0 = times[0];
  const t1 = times[times.length - 1];
  const x = (t: number) => ((t - t0) / (t1 - t0 || 1)) * width;
  const y = (v: number) => pad + (1 - (v - lo) / (hi - lo)) * (height - pad * 2);

  const paths = series.map((s) => {
    let d = "";
    let pen = false;
    s.values.forEach((v, i) => {
      if (v === null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(times[i]).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    return d;
  });

  const lastValues = series.map((s) => [...s.values].reverse().find((v) => v !== null) ?? null);
  const summary = series.map((s, i) => `${s.label} ${lastValues[i] ?? "–"}${unit}`).join(", ");

  return (
    <svg
      role="img"
      aria-label={`${label}. Latest: ${summary}`}
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={series[0].color} stopOpacity="0.22" />
          <stop offset="1" stopColor={series[0].color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {band && (
        <rect x={0} width={width} y={y(band.to)} height={Math.max(0, y(band.from) - y(band.to))} fill={band.color} opacity={0.1} />
      )}
      {series[0].fill && paths[0] && (
        <path d={`${paths[0]} L${x(t1)} ${height} L${x(times[series[0].values.findIndex((v) => v !== null)] ?? t0)} ${height} Z`} fill={`url(#${gradientId})`} />
      )}
      {series.map((s, i) => (
        <path
          key={s.label}
          d={paths[i]}
          fill="none"
          stroke={s.color}
          strokeWidth={2.2}
          strokeDasharray={s.dashed ? "5 6" : undefined}
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}

/** Decorative contour lines behind the content. */
export function Topo() {
  return (
    <svg className="topo" aria-hidden="true" viewBox="0 0 1200 520" preserveAspectRatio="xMidYMin slice">
      <g fill="none" stroke="#5E664F" strokeWidth="1">
        <path d="M-20 90 C 200 30, 420 150, 640 80 S 1000 20, 1220 90" />
        <path d="M-20 140 C 210 80, 430 200, 650 130 S 1010 70, 1220 140" />
        <path d="M-20 195 C 220 135, 440 255, 660 185 S 1020 125, 1220 195" />
        <path d="M-20 255 C 230 195, 450 315, 670 245 S 1030 185, 1220 255" />
        <path d="M120 330 C 230 280, 400 300, 440 350 S 300 440, 200 410 S 60 370, 120 330 Z" />
        <path d="M180 345 C 250 315, 360 330, 385 360 S 280 410, 225 395 S 140 370, 180 345 Z" />
        <path d="M-20 470 C 260 420, 520 500, 780 440 S 1080 410, 1220 450" />
      </g>
    </svg>
  );
}
