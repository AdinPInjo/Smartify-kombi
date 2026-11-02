import { Car, SunMedium, Zap } from "lucide-react";
import { useState } from "react";
import { useEnergy, useEnergyHistory, useWater } from "@/api/hooks";
import type { EnergyDevice } from "@/api/types";
import { batteryColor, LineChart, RingGauge } from "@/components/instruments";
import { PageHeader } from "@/components/PageHeader";
import { Card, Num, Segmented, Skeleton } from "@/components/ui";
import { ago, duration, fmt, humanize, signed } from "@/lib/format";

const RANGES = [
  { value: "6", label: "6 h" },
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
];

export function Energy() {
  const energy = useEnergy();
  const water = useWater();
  const [hours, setHours] = useState("24");
  const history = useEnergyHistory(Number(hours));
  const e = energy.data;
  const battery = e?.battery;
  const soc = battery?.soc ?? null;
  const points = history.data ?? [];
  const times = points.map((p) => p.created_at);

  return (
    <main className="page">
      <PageHeader kicker="Energy" title="Battery & charging" sub={e?.available ? `${e.devices.length} Victron devices` : undefined} />

      {energy.isPending && <Skeleton height={240} />}

      {e && !e.available && (
        <Card label="Victron">
          <p className="muted" style={{ margin: 0 }}>
            No Victron device is reporting. Add SmartShunt, MPPT, Orion and MultiPlus to <code>SMARTIFY_VICTRON_DEVICES</code> in{" "}
            <code>.env</code> (name|MAC|key from VictronConnect › Product info › Instant readout).
          </p>
          {water.data?.battery_voltage != null && (
            <div className="row">
              <span className="muted small">Battery voltage from the water sensor supply:</span>
              <Num value={fmt(water.data.battery_voltage, 2)} unit="V" size="s" />
            </div>
          )}
        </Card>
      )}

      {e?.available && battery && (
        <>
          <div className="grid">
            <Card label="House battery">
              <div className="row" style={{ gap: 20, flexWrap: "wrap", justifyContent: "center" }}>
                <RingGauge value={soc} size={190} stroke={14} color={batteryColor(soc)} label={`Battery ${soc ?? "unknown"} percent`}>
                  <Num value={soc !== null ? Math.round(soc) : "–"} unit="%" size="xl" />
                  <span className="small muted">
                    {battery.remaining_mins ? `~${duration(battery.remaining_mins * 60)} left` : (battery.current ?? 0) > 0 ? "charging" : ""}
                  </span>
                </RingGauge>
                <div className="stack" style={{ gap: 12, minWidth: 140 }}>
                  <Stat label="Voltage" value={fmt(battery.voltage, 2)} unit="V" />
                  <Stat
                    label="Current"
                    value={signed(battery.current)}
                    unit="A"
                    className={(battery.current ?? 0) < 0 ? "c-alert" : "c-ok"}
                  />
                  <Stat label="Power" value={signed(battery.power, 0)} unit="W" />
                  {battery.consumed_ah !== null && <Stat label="Consumed" value={fmt(battery.consumed_ah, 1)} unit="Ah" />}
                </div>
              </div>
              {(battery.starter_voltage !== null || (battery.alarm && battery.alarm !== "no_alarm")) && (
                <div className="row-between divider small">
                  {battery.starter_voltage !== null && (
                    <span className="muted">
                      Starter battery <strong style={{ color: "var(--text)" }}>{fmt(battery.starter_voltage, 2)} V</strong>
                    </span>
                  )}
                  {battery.alarm && battery.alarm !== "no_alarm" && <span className="c-danger">Alarm: {humanize(battery.alarm)}</span>}
                </div>
              )}
            </Card>

            <div className="stack" style={{ gap: "var(--gap)" }}>
              {e.solar && (
                <Source
                  icon={<SunMedium size={22} color="var(--solar)" aria-hidden="true" />}
                  title="Solar"
                  value={fmt(e.solar.power, 0)}
                  unit="W"
                  active={(e.solar.power ?? 0) > 0}
                  detail={`${humanize(e.solar.charge_state)} · today ${fmt((e.solar.yield_today_wh ?? 0) / 1000, 2)} kWh`}
                  error={e.solar.error && e.solar.error !== "no_error" ? humanize(e.solar.error) : null}
                />
              )}
              {e.dcdc && (
                <Source
                  icon={<Car size={22} color="var(--accent)" aria-hidden="true" />}
                  title="Alternator (Orion)"
                  value={fmt(e.dcdc.output_current, 1)}
                  unit="A"
                  active={Boolean(e.dcdc.charge_state && e.dcdc.charge_state !== "off")}
                  detail={`${humanize(e.dcdc.charge_state)} · in ${fmt(e.dcdc.input_voltage, 2)} V → out ${fmt(e.dcdc.output_voltage, 2)} V${
                    e.dcdc.charge_state === "off" && e.dcdc.off_reason ? ` · ${humanize(e.dcdc.off_reason)}` : ""
                  }`}
                />
              )}
              {e.inverter && (
                <Source
                  icon={<Zap size={22} aria-hidden="true" />}
                  title="MultiPlus"
                  value={fmt(e.inverter.ac_out_power, 0)}
                  unit="W"
                  active={(e.inverter.ac_out_power ?? 0) > 0}
                  detail={`${humanize(e.inverter.state)} · shore ${humanize(e.inverter.ac_in_state)}${
                    (e.inverter.ac_in_power ?? 0) > 0 ? ` (${e.inverter.ac_in_power} W in)` : ""
                  }`}
                  error={e.inverter.alarm && e.inverter.alarm !== "no_alarm" ? humanize(e.inverter.alarm) : null}
                />
              )}
            </div>
          </div>

          <Card label="History" action={<div style={{ width: 230 }}><Segmented label="Time range" options={RANGES} value={hours} onChange={setHours} /></div>}>
            <div className="stack" style={{ gap: 4 }}>
              <span className="small muted">Battery %</span>
              <LineChart
                label="Battery charge"
                unit="%"
                times={times}
                min={0}
                max={100}
                series={[{ label: "Battery", values: points.map((p) => p.battery_soc), color: "var(--ok)", fill: true }]}
              />
              <span className="small muted">Solar power</span>
              <LineChart
                label="Solar power"
                unit=" W"
                height={80}
                min={0}
                times={times}
                series={[{ label: "Solar", values: points.map((p) => p.solar_power), color: "var(--solar)", fill: true }]}
              />
              <span className="small muted">Battery voltage</span>
              <LineChart
                label="Battery voltage"
                unit=" V"
                height={80}
                times={times}
                series={[{ label: "Voltage", values: points.map((p) => p.battery_voltage), color: "var(--text)" }]}
              />
            </div>
          </Card>

          <Card label="Devices">
            <div className="list">
              {e.devices.map((device) => (
                <DeviceRow key={device.device} device={device} />
              ))}
            </div>
          </Card>
        </>
      )}
    </main>
  );
}

function Stat({ label, value, unit, className = "" }: { label: string; value: string; unit: string; className?: string }) {
  return (
    <div className="stack" style={{ gap: 2 }}>
      <span className="tiny muted">{label}</span>
      <Num value={value} unit={unit} size="m" className={className} />
    </div>
  );
}

function Source({
  icon,
  title,
  value,
  unit,
  detail,
  active,
  error,
}: {
  icon: React.ReactNode;
  title: string;
  value: string;
  unit: string;
  detail: string;
  active: boolean;
  error?: string | null;
}) {
  return (
    <section className={`card ${active ? "highlight" : ""}`} style={{ gap: 6 }}>
      <div className="row-between">
        <span className="row">
          {icon}
          <span>{title}</span>
        </span>
        <Num value={value} unit={unit} size="l" />
      </div>
      <span className="small muted">{detail}</span>
      {error && <span className="small c-danger">Error: {error}</span>}
    </section>
  );
}

function DeviceRow({ device }: { device: EnergyDevice }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <button
        type="button"
        className="row-between"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        style={{ background: "none", border: 0, padding: 0, cursor: "pointer", textAlign: "left", minHeight: 44 }}
      >
        <span className="row">
          <span className={`dot ${device.stale ? "bad" : "ok"}`} />
          <span>
            <strong>{device.device}</strong> <span className="muted small">{device.model ?? humanize(device.kind)}</span>
          </span>
        </span>
        <span className="small muted">
          {device.stale ? `silent ${ago(device.updated_at)}` : `${device.rssi ?? "–"} dBm`} {open ? "▴" : "▾"}
        </span>
      </button>
      {open && (
        <div className="table-wrap">
          <table>
            <tbody>
              {Object.entries(device.values).map(([key, value]) => (
                <tr key={key}>
                  <td className="muted">{humanize(key)}</td>
                  <td className="mono">{typeof value === "string" ? humanize(value) : (value ?? "–")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
