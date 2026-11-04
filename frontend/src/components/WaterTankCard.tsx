// The fresh water tank: level now and its history (Energy & water page).
import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useWater, useWaterHistory } from "@/api/hooks";
import { LineChart, Tank } from "./instruments";
import { Num, Segmented } from "./ui";
import { ago } from "@/lib/format";

const RANGES = [
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
];

export function WaterTankCard() {
  const water = useWater();
  const [hours, setHours] = useState("24");
  const history = useWaterHistory(Number(hours));
  const points = history.data ?? [];
  const level = water.data?.level_percent ?? null;
  const missing = water.data?.error?.includes("Sensors tab");
  const ref = useRef<HTMLElement>(null);
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === "#water") ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash]);
  return (
    <section id="water" ref={ref} className="card" style={{ scrollMarginTop: 16 }}>
      <div className="row-between">
        <h2 className="label" style={{ margin: 0 }}>Fresh water</h2>
        {!missing && (
          <div style={{ width: 170 }}>
            <Segmented label="Time range" options={RANGES} value={hours} onChange={setHours} />
          </div>
        )}
      </div>
      {missing ? (
        <p className="small muted" style={{ margin: 0 }}>
          No water tank sensor yet. <Link to="/sensors">Add it in the Sensors tab ›</Link>
        </p>
      ) : (
        <>
          <div className="row" style={{ gap: 18, alignItems: "flex-end" }}>
            <Tank percent={level} height={130} width={54} />
            <div className="stack" style={{ gap: 4 }}>
              <Num value={level ?? "–"} unit="%" size="xl" />
              <span className={`small ${water.data?.ok ? "muted" : "c-accent"}`}>
                {water.data?.ok ? `Updated ${ago(water.data.updated_at)}` : (water.data?.error ?? "No reading yet")}
              </span>
              <Link to="/sensors" className="tiny">Calibrate in the Sensors tab ›</Link>
            </div>
          </div>
          <LineChart
            label="Water level"
            unit="%"
            height={90}
            times={points.map((p) => p.created_at)}
            min={0}
            max={100}
            series={[{ label: "Level", values: points.map((p) => p.level_percent), color: "var(--water)", fill: true }]}
          />
        </>
      )}
    </section>
  );
}
