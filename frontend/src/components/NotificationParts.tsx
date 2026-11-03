// Building blocks of the Alerts tab: alert switches, theft alert, quiet hours, history.
import { BatteryLow, Droplets, ShieldAlert, Thermometer, Wrench } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useClimate, useNotificationAction, useNotificationHistory, useSendTest } from "@/api/hooks";
import type { NotificationEntry, NotificationSettings, NotifyChannel } from "@/api/types";
import { Field, useErrorToast, useToast } from "./ui";
import { ago, clock } from "@/lib/format";

export type Patch = Record<string, unknown>;

/** PATCH /notifications/settings with error toast. */
export function useNotifyPatch() {
  const action = useNotificationAction();
  const showError = useErrorToast();
  return {
    pending: action.isPending,
    patch: (body: Patch, onDone?: () => void) =>
      action.mutate({ path: "/settings", method: "patch", body }, { onError: showError, onSuccess: () => onDone?.() }),
  };
}

export const CHANNEL_NAMES: Record<NotifyChannel, string> = { ntfy: "ntfy", telegram: "Telegram" };

export function TestButton({
  channel,
  disabled,
  primary,
  onResult,
}: {
  channel: NotifyChannel;
  disabled?: boolean;
  primary?: boolean;
  onResult?: (error: string | null) => void;
}) {
  const test = useSendTest();
  const toast = useToast();
  return (
    <button
      type="button"
      className={`btn ${primary ? "primary" : "small"}`}
      disabled={disabled || test.isPending}
      onClick={() =>
        test.mutate(channel, {
          onSuccess: () => {
            if (!onResult) toast("Test sent, check your phone");
            onResult?.(null);
          },
          onError: (error) => {
            const message = error instanceof Error ? error.message : String(error);
            if (!onResult) toast(message, true);
            onResult?.(message);
          },
        })
      }
    >
      {test.isPending ? "Sending…" : "Send a test notification"}
    </button>
  );
}

// --- alert switches -----------------------------------------------------------------------

export function NumberSetting({
  value,
  unit,
  min,
  max,
  step = 1,
  onSave,
  label,
  allowEmpty = false,
}: {
  value: number | null;
  unit: string;
  min: number;
  max: number;
  step?: number;
  onSave: (value: number | null) => void;
  label: string;
  allowEmpty?: boolean;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const next = text.trim() === "" ? null : Number(text);
    if (next === null && !allowEmpty) return setText(value === null ? "" : String(value));
    if (next === value || (next !== null && (Number.isNaN(next) || next < min || next > max))) {
      return setText(value === null ? "" : String(value));
    }
    onSave(next);
  };
  return (
    <span className="row" style={{ gap: 6 }}>
      <input
        className="input"
        type="number"
        inputMode="decimal"
        aria-label={label}
        style={{ width: 84, minHeight: 38 }}
        min={min}
        max={max}
        step={step}
        value={text}
        placeholder={allowEmpty ? "auto" : undefined}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLInputElement).blur()}
      />
      <span className="small muted">{unit}</span>
    </span>
  );
}

function AlertRow({
  label,
  description,
  enabled,
  onToggle,
  children,
  always,
}: {
  label: string;
  description: string;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  children?: ReactNode;
  always?: boolean;
}) {
  return (
    <div className="alert-row">
      <label className="alert-toggle">
        <input type="checkbox" checked={enabled} onChange={(e) => onToggle(e.target.checked)} />
        <span className="stack" style={{ gap: 2 }}>
          <span className={enabled ? "" : "muted"}>
            {label}
            {always && enabled && <span className="tag">day & night</span>}
          </span>
          <span className="tiny faint">{description}</span>
        </span>
      </label>
      {enabled && children && <div className="alert-setting">{children}</div>}
    </div>
  );
}

function Group({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="stack" style={{ gap: 2 }}>
      <h3 className="label row" style={{ margin: "6px 0 0", gap: 8 }}>
        {icon}
        {title}
      </h3>
      <div className="list">{children}</div>
    </div>
  );
}

/** Every alert, grouped, with a plain-language description. */
export function AlertGroups({ settings, includeTheft = true }: { settings: NotificationSettings; includeTheft?: boolean }) {
  const { patch } = useNotifyPatch();
  const a = settings.alerts;
  const climate = useClimate();
  const sensors = climate.data?.map((c) => c.sensor) ?? [];
  const set = (alert: string, changes: Patch) => patch({ alerts: { [alert]: changes } });
  const toggle = (alert: string) => (enabled: boolean) => set(alert, { enabled });
  const sensorPicker = (alert: "cold_inside" | "hot_inside") =>
    sensors.length > 1 && (
      <select
        className="input"
        style={{ width: "auto", minHeight: 38 }}
        aria-label="Sensor"
        value={a[alert].sensor || sensors[0]}
        onChange={(e) => set(alert, { sensor: e.target.value })}
      >
        {sensors.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    );

  return (
    <div className="stack" style={{ gap: 14 }}>
      <Group icon={<BatteryLow size={16} aria-hidden="true" />} title="Battery & power">
        <AlertRow
          label="Battery low"
          description="The house battery drops below this charge."
          enabled={a.battery_low.enabled}
          onToggle={toggle("battery_low")}
        >
          <span className="small muted">below</span>
          <NumberSetting label="Battery below" value={a.battery_low.threshold} unit="%" min={1} max={99} onSave={(v) => set("battery_low", { threshold: v })} />
        </AlertRow>
        <AlertRow
          label="Battery forecast"
          description="Warns ahead of time: your usage and tomorrow's sun say the battery will get this low within 36 hours."
          enabled={a.energy_forecast.enabled}
          onToggle={toggle("energy_forecast")}
        >
          <span className="small muted">below</span>
          <NumberSetting label="Forecast below" value={a.energy_forecast.threshold} unit="%" min={1} max={99} onSave={(v) => set("energy_forecast", { threshold: v })} />
        </AlertRow>
        <AlertRow
          label="Not charging while driving"
          description="After 10 minutes of driving the battery still isn't charging: check the DC-DC charger and its fuse."
          enabled={a.battery_not_charging.enabled}
          onToggle={toggle("battery_not_charging")}
        />
      </Group>

      <Group icon={<Thermometer size={16} aria-hidden="true" />} title="Climate">
        <AlertRow
          label="Cold inside"
          description="Freezing water pipes, or a cold pet."
          enabled={a.cold_inside.enabled}
          onToggle={toggle("cold_inside")}
          always
        >
          {sensorPicker("cold_inside")}
          <span className="small muted">below</span>
          <NumberSetting label="Colder than" value={a.cold_inside.threshold} unit="°C" min={-30} max={30} step={0.5} onSave={(v) => set("cold_inside", { threshold: v })} />
        </AlertRow>
        <AlertRow
          label="Hot inside"
          description="Too hot for pets left in the van."
          enabled={a.hot_inside.enabled}
          onToggle={toggle("hot_inside")}
          always
        >
          {sensorPicker("hot_inside")}
          <span className="small muted">above</span>
          <NumberSetting label="Hotter than" value={a.hot_inside.threshold} unit="°C" min={15} max={60} step={0.5} onSave={(v) => set("hot_inside", { threshold: v })} />
        </AlertRow>
        <AlertRow
          label="Frost tonight"
          description="In the late afternoon, when the forecast for where the van stands goes this low overnight."
          enabled={a.frost_forecast.enabled}
          onToggle={toggle("frost_forecast")}
        >
          <span className="small muted">at or below</span>
          <NumberSetting label="Forecast at or below" value={a.frost_forecast.threshold} unit="°C" min={-30} max={10} onSave={(v) => set("frost_forecast", { threshold: v })} />
        </AlertRow>
      </Group>

      <Group icon={<Droplets size={16} aria-hidden="true" />} title="Water">
        <AlertRow
          label="Water tank almost empty"
          description="Fresh water drops below this level."
          enabled={a.water_low.enabled}
          onToggle={toggle("water_low")}
        >
          <span className="small muted">below</span>
          <NumberSetting label="Water below" value={a.water_low.threshold} unit="%" min={1} max={99} onSave={(v) => set("water_low", { threshold: v })} />
        </AlertRow>
      </Group>

      {includeTheft && (
        <Group icon={<ShieldAlert size={16} aria-hidden="true" />} title="Security">
          <AlertRow
            label="The van is moving"
            description="It drives off after standing still. Settings in the theft alert card."
            enabled={a.departure.enabled}
            onToggle={toggle("departure")}
            always
          />
        </Group>
      )}

      <Group icon={<Wrench size={16} aria-hidden="true" />} title="System">
        <AlertRow
          label="Something stopped working"
          description="A temperature sensor, the GPS or a Victron device stops reporting."
          enabled={a.sensor_fault.enabled}
          onToggle={toggle("sensor_fault")}
        />
        <AlertRow
          label="Safety cutoff"
          description="A relay was switched off because it got too hot."
          enabled={a.relay_cutoff.enabled}
          onToggle={toggle("relay_cutoff")}
          always
        />
      </Group>

      <details>
        <summary className="small muted" style={{ cursor: "pointer", minHeight: 36 }}>
          Battery forecast: battery size and solar panels
        </summary>
        <div className="grid-2" style={{ marginTop: 8 }}>
          <Field label="Battery capacity" hint="Leave empty to estimate it from the SmartShunt.">
            <NumberSetting allowEmpty label="Battery capacity" value={a.energy_forecast.battery_capacity_ah} unit="Ah" min={1} max={5000} onSave={(v) => set("energy_forecast", { battery_capacity_ah: v })} />
          </Field>
          <Field label="Solar panels" hint="Leave empty to use the most solar power seen recently.">
            <NumberSetting allowEmpty label="Solar panels" value={a.energy_forecast.solar_peak_w} unit="W" min={0} max={10000} onSave={(v) => set("energy_forecast", { solar_peak_w: v })} />
          </Field>
        </div>
      </details>
    </div>
  );
}

// --- theft alert -----------------------------------------------------------------------------

export function TheftCard({ settings }: { settings: NotificationSettings }) {
  const d = settings.alerts.departure;
  const { patch } = useNotifyPatch();
  const action = useNotificationAction();
  const showError = useErrorToast();
  const set = (changes: Patch) => patch({ alerts: { departure: changes } });
  const now = Date.now() / 1000;
  const paused = d.paused_until !== null && d.paused_until > now;
  const pause = (hours: number) => action.mutate({ path: "/departure/pause", body: { hours } }, { onError: showError });

  return (
    <section className="card" id="theft">
      <div className="row-between">
        <h2 className="label row" style={{ margin: 0, gap: 8 }}>
          <ShieldAlert size={16} aria-hidden="true" /> Theft alert
        </h2>
        <span className="chip">
          <span className={`dot ${!d.enabled ? "off" : paused ? "warn" : "ok"}`} />
          {!d.enabled ? "off" : paused ? `paused until ${clock(d.paused_until!)}` : "watching"}
        </span>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        When the van drives off after standing still, you get an urgent notification with a map link, also at night. There's
        nothing to switch on when you leave: if it's you driving, ignore it or pause it here first.
      </p>
      <label className="switch-row">
        <span>Send theft alerts</span>
        <input type="checkbox" checked={d.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
      </label>
      {d.enabled && (
        <>
          <div className="row-between wrap">
            <span className="small">Only after standing still for at least</span>
            <NumberSetting label="Parked at least" value={d.after_minutes} unit="min" min={5} max={1440} onSave={(v) => set({ after_minutes: v ?? 30 })} />
          </div>
          <label className="row small wrap" style={{ cursor: "pointer", gap: 8 }}>
            <input type="checkbox" checked={d.night_only} onChange={(e) => set({ night_only: e.target.checked })} className="check" />
            <span>Only at night, from</span>
            <input className="input time" type="time" value={d.night_from} onChange={(e) => e.target.value && set({ night_from: e.target.value })} disabled={!d.night_only} />
            <span>to</span>
            <input className="input time" type="time" value={d.night_to} onChange={(e) => e.target.value && set({ night_to: e.target.value })} disabled={!d.night_only} />
          </label>
          <div className="row wrap" style={{ gap: 8 }}>
            {paused ? (
              <button type="button" className="btn small" onClick={() => pause(0)}>
                Resume theft alerts now
              </button>
            ) : (
              <>
                <span className="small muted">I'm driving, pause for</span>
                {[2, 12, 24].map((hours) => (
                  <button key={hours} type="button" className="btn small" onClick={() => pause(hours)}>
                    {hours} h
                  </button>
                ))}
              </>
            )}
          </div>
          <p className="tiny faint" style={{ margin: 0 }}>
            The van needs its own internet to warn you while you're away. A phone hotspot leaves with your phone, so a small
            4G router with a SIM card in the van is best.
          </p>
        </>
      )}
    </section>
  );
}

// --- quiet hours ---------------------------------------------------------------------------------

export function QuietHoursCard({ settings }: { settings: NotificationSettings }) {
  const { patch } = useNotifyPatch();
  const q = settings.quiet_hours;
  return (
    <section className="card">
      <h2 className="label" style={{ margin: 0 }}>Quiet hours</h2>
      <label className="row small wrap" style={{ cursor: "pointer", gap: 8 }}>
        <input type="checkbox" checked={q.enabled} onChange={(e) => patch({ quiet_hours: { enabled: e.target.checked } })} className="check" />
        <span>Hold normal messages from</span>
        <input className="input time" type="time" value={q.from} onChange={(e) => e.target.value && patch({ quiet_hours: { from: e.target.value } })} disabled={!q.enabled} />
        <span>to</span>
        <input className="input time" type="time" value={q.to} onChange={(e) => e.target.value && patch({ quiet_hours: { to: e.target.value } })} disabled={!q.enabled} />
      </label>
      <span className="tiny faint">They arrive in the morning instead. Alerts marked “day & night” always come through.</span>
      <Field label="While a problem lasts">
        <select className="input" value={settings.repeat_hours} onChange={(e) => patch({ repeat_hours: Number(e.target.value) })}>
          <option value={0}>Tell me once</option>
          <option value={2}>Remind me every 2 hours</option>
          <option value={6}>Remind me every 6 hours</option>
          <option value={12}>Remind me every 12 hours</option>
        </select>
      </Field>
    </section>
  );
}

// --- history ----------------------------------------------------------------------------------------

function statusText(entry: NotificationEntry): string {
  if (entry.status === "sent") return `delivered ${ago(entry.sent_at)}`;
  if (entry.status === "dropped") return `not sent: ${entry.last_error ?? "dropped"}`;
  if (entry.next_attempt_at > Date.now() / 1000 && !entry.attempts) return `held for quiet hours, goes out at ${clock(entry.next_attempt_at)}`;
  return `waiting for internet${entry.last_error ? ` (${entry.last_error})` : ""}`;
}

export function HistoryCard() {
  const history = useNotificationHistory();
  const entries = history.data ?? [];
  return (
    <section className="card">
      <h2 className="label" style={{ margin: 0 }}>Recent notifications</h2>
      {entries.length === 0 ? (
        <span className="small muted">Nothing sent yet. Everything the van tells you shows up here too.</span>
      ) : (
        <div className="list">
          {entries.map((entry) => (
            <div key={entry.id} className="stack" style={{ gap: 3 }}>
              <div className="row-between" style={{ alignItems: "baseline" }}>
                <strong className="small">{entry.title}</strong>
                <span className="tiny faint" style={{ whiteSpace: "nowrap" }}>{ago(entry.created_at)}</span>
              </div>
              <span className="small muted">{entry.message}</span>
              <span className={`tiny row ${entry.status === "dropped" ? "c-danger" : "faint"}`} style={{ gap: 6 }}>
                <span className={`dot ${entry.status === "sent" ? "ok" : entry.status === "dropped" ? "bad" : "warn"}`} style={{ width: 7, height: 7 }} />
                {statusText(entry)}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
