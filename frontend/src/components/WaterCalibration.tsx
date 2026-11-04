// Water level calibration: mark the tank empty and full from the live reading.
// On the Climate page, next to the tank it calibrates.
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useCalibrateWater, useMode, useUpdateWaterSettings, useWater, useWaterSettings } from "@/api/hooks";
import { OnlyOnVan } from "./RemoteBanner";
import { Field, Segmented, useErrorToast, useToast } from "./ui";
import { fmt } from "@/lib/format";

export function WaterCalibration() {
  const { cloud } = useMode();
  const settings = useWaterSettings();
  const water = useWater();
  const calibrate = useCalibrateWater();
  const update = useUpdateWaterSettings();
  const showError = useErrorToast();
  const toast = useToast();
  const s = settings.data;
  const ref = useRef<HTMLElement>(null);
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === "#water-calibration") ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash]);
  const [divider, setDivider] = useState({ top: "", bottom: "" });
  useEffect(() => {
    if (s) setDivider({ top: String(s.divider_r_top), bottom: String(s.divider_r_bottom) });
  }, [s?.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const mark = (point: "empty" | "full") => {
    if (!window.confirm(`Is the tank really ${point} right now? The current reading becomes the ${point} point.`)) return;
    calibrate.mutate(point, { onSuccess: () => toast(`${point === "full" ? "Full" : "Empty"} point saved`), onError: showError });
  };

  return (
    <section id="water-calibration" ref={ref} className="card" style={{ scrollMarginTop: 16 }}>
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
