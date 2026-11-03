import { useMemo, useState, type FormEvent } from "react";
import { useClimate, useEnergy, useSaveRule, type RuleInput } from "@/api/hooks";
import type { Condition, Metric, OnOff, Rule } from "@/api/types";
import { METRIC_LABELS, METRIC_UNITS } from "@/lib/format";
import { Dialog, ErrorNote, Field, Segmented, useToast } from "./ui";

// Which Victron device kinds provide each energy metric (mirrors backend/services/energy.py).
const METRIC_KINDS: Record<string, string[]> = {
  battery_soc: ["battery_monitor", "inverter_charger"],
  battery_voltage: ["battery_monitor", "inverter_charger", "solar_charger"],
  battery_current: ["battery_monitor", "inverter_charger"],
  solar_power: ["solar_charger"],
};

type Compare = "below" | "above" | "between";
type Choice = Metric | "schedule";

const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

interface SimpleRule {
  metric: Choice;
  sensor: string;
  compare: Compare;
  value: string;
  max: string;
  /** Only between `from` and `to` (always on for "schedule"). */
  window: boolean;
  from: string;
  to: string;
  /** Days the window starts on, 0 = Monday. Empty = every day. */
  days: number[];
}

type TimeCondition = Extract<Condition, { type: "time" }>;
type LeafCondition = Extract<Condition, { type: "threshold" | "range" }>;

const NO_WINDOW = { window: false, from: "06:00", to: "09:00", days: [] as number[] };

function leafToSimple(condition: LeafCondition): SimpleRule {
  if (condition.type === "threshold") {
    return {
      metric: condition.metric,
      sensor: condition.sensor,
      compare: condition.op.startsWith("<") ? "below" : "above",
      value: String(condition.value),
      max: "",
      ...NO_WINDOW,
    };
  }
  return { metric: condition.metric, sensor: condition.sensor, compare: "between", value: String(condition.min), max: String(condition.max), ...NO_WINDOW };
}

function windowOf(time: TimeCondition) {
  return { window: true, from: time.from, to: time.to, days: time.days ?? [] };
}

/** Rules made in this editor are one comparison and/or a time window; anything else is edited as JSON. */
function toSimple(condition: Condition | undefined): SimpleRule | null {
  if (!condition) return null;
  if (condition.type === "threshold" || condition.type === "range") return leafToSimple(condition);
  if (condition.type === "time") {
    return { metric: "schedule", sensor: "", compare: "below", value: "", max: "", ...windowOf(condition) };
  }
  if (condition.type === "all" && condition.conditions.length === 2) {
    const leaf = condition.conditions.find((c): c is LeafCondition => c.type === "threshold" || c.type === "range");
    const time = condition.conditions.find((c): c is TimeCondition => c.type === "time");
    if (leaf && time) return { ...leafToSimple(leaf), ...windowOf(time) };
  }
  return null;
}

function fromSimple(rule: SimpleRule): Condition {
  const time: TimeCondition = { type: "time", from: rule.from, to: rule.to, ...(rule.days.length ? { days: rule.days } : {}) };
  if (rule.metric === "schedule") return time;
  const leaf: Condition =
    rule.compare === "between"
      ? { type: "range", metric: rule.metric, sensor: rule.sensor, min: Number(rule.value), max: Number(rule.max) }
      : { type: "threshold", metric: rule.metric, sensor: rule.sensor, op: rule.compare === "below" ? "<" : ">", value: Number(rule.value) };
  return rule.window ? { type: "all", conditions: [leaf, time] } : leaf;
}

function daysText(days: number[] | undefined): string {
  if (!days || days.length === 0 || days.length === 7) return "";
  if (days.join() === "0,1,2,3,4") return " on weekdays";
  if (days.join() === "5,6") return " at weekends";
  return ` on ${days.map((d) => DAY_NAMES[d]).join(", ")}`;
}

export function describeCondition(condition: Condition): string {
  switch (condition.type) {
    case "threshold": {
      const unit = METRIC_UNITS[condition.metric] ?? "";
      const word = condition.op.startsWith("<") ? "below" : "above";
      return `${condition.sensor} ${METRIC_LABELS[condition.metric]?.toLowerCase() ?? condition.metric} ${word} ${condition.value}${unit === "%" ? "%" : ` ${unit}`}`;
    }
    case "range": {
      const unit = METRIC_UNITS[condition.metric] ?? "";
      return `${condition.sensor} ${METRIC_LABELS[condition.metric]?.toLowerCase() ?? condition.metric} between ${condition.min} and ${condition.max} ${unit}`;
    }
    case "all":
      return condition.conditions.map(describeCondition).join(" and ");
    case "any":
      return condition.conditions.map(describeCondition).join(" or ");
    case "not":
      return `not (${describeCondition(condition.condition)})`;
    case "always":
      return "always";
    case "time":
      return `between ${condition.from} and ${condition.to}${daysText(condition.days)}`;
  }
}

export function RuleEditor({ relayId, rule, onClose }: { relayId: string; rule?: Rule; onClose: () => void }) {
  const save = useSaveRule(relayId);
  const toast = useToast();
  const climate = useClimate();
  const energy = useEnergy();

  const initial = toSimple(rule?.condition);
  const [advanced, setAdvanced] = useState(Boolean(rule) && !initial);
  const [name, setName] = useState(rule?.name ?? "");
  const [action, setAction] = useState<OnOff>(rule?.action ?? "on");
  const [simple, setSimple] = useState<SimpleRule>(
    initial ?? { metric: "temperature", sensor: climate.data?.[0]?.sensor ?? "", compare: "below", value: "8", max: "", ...NO_WINDOW },
  );
  const [json, setJson] = useState(JSON.stringify(rule?.condition ?? fromSimple(simple), null, 2));
  const [priority, setPriority] = useState(String(rule?.priority ?? 100));
  const [cooldown, setCooldown] = useState(String(Math.round((rule?.cooldown_seconds ?? 60) / 60)));
  const [jsonError, setJsonError] = useState<string | null>(null);

  const sensors = useMemo(() => {
    if (simple.metric === "schedule") return [];
    if (simple.metric === "temperature" || simple.metric === "humidity") return climate.data?.map((s) => s.sensor) ?? [];
    if (simple.metric === "water_level") return ["tank"];
    if (simple.metric === "speed") return ["gps"];
    const kinds = METRIC_KINDS[simple.metric] ?? [];
    return energy.data?.devices.filter((d) => kinds.includes(d.kind)).map((d) => d.device) ?? [];
  }, [simple.metric, climate.data, energy.data]);

  const update = (changes: Partial<SimpleRule>) => setSimple((s) => ({ ...s, ...changes }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    let condition: Condition;
    if (advanced) {
      try {
        condition = JSON.parse(json);
        setJsonError(null);
      } catch (e) {
        setJsonError(`Not valid JSON: ${(e as Error).message}`);
        return;
      }
    } else {
      condition = fromSimple({ ...simple, sensor: simple.sensor || sensors[0] || "" });
    }
    const body: RuleInput = {
      name: name.trim() || describeCondition(condition),
      condition,
      action,
      priority: Number(priority),
      cooldown_seconds: Math.round(Number(cooldown) * 60),
      enabled: rule?.enabled ?? true,
    };
    save.mutate(
      { id: rule?.id, rule: body },
      {
        onSuccess: () => {
          toast(rule ? "Rule saved" : "Rule added");
          // On the remote dashboard the change reaches the van on its next sync.
          onClose();
        },
      },
    );
  };

  const unit = simple.metric === "schedule" ? "" : METRIC_UNITS[simple.metric];
  const schedule = simple.metric === "schedule";
  const toggleDay = (day: number) =>
    update({ days: simple.days.includes(day) ? simple.days.filter((d) => d !== day) : [...simple.days, day].sort() });
  const timeInputs = (
    <div className="stack" style={{ gap: 10 }}>
      <div className="grid-2">
        <Field label="From">
          <input className="input" type="time" required value={simple.from} onChange={(e) => update({ from: e.target.value })} />
        </Field>
        <Field label="To">
          <input className="input" type="time" required value={simple.to} onChange={(e) => update({ to: e.target.value })} />
        </Field>
      </div>
      <div className="row" style={{ gap: 4, flexWrap: "wrap" }} role="group" aria-label="Days">
        {DAYS.map((label, day) => (
          <button
            key={label}
            type="button"
            className="btn small"
            aria-pressed={simple.days.includes(day)}
            style={simple.days.includes(day) ? { background: "var(--line-strong)" } : { color: "var(--muted)" }}
            onClick={() => toggleDay(day)}
          >
            {label}
          </button>
        ))}
        <span className="tiny faint" style={{ alignSelf: "center" }}>{simple.days.length ? "" : "every day"}</span>
      </div>
      <span className="tiny faint">A window past midnight (e.g. 22:00 to 06:00) works. Uses the Pi's clock.</span>
    </div>
  );

  return (
    <Dialog title={rule ? "Edit rule" : "New rule"} onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        {!advanced ? (
          <>
            <div className="grid-2">
              <Field label="When">
                <select className="input" value={simple.metric} onChange={(e) => update({ metric: e.target.value as Choice, sensor: "" })}>
                  {Object.entries(METRIC_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                  <option value="schedule">Time of day (schedule)</option>
                </select>
              </Field>
              {!schedule && (
              <Field label="of">
                <select className="input" value={simple.sensor || sensors[0] || ""} onChange={(e) => update({ sensor: e.target.value })}>
                  {sensors.length === 0 && <option value="">no source available</option>}
                  {sensors.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              )}
            </div>
            {schedule ? (
              timeInputs
            ) : (
            <>
            <Segmented<Compare>
              label="Comparison"
              value={simple.compare}
              onChange={(compare) => update({ compare })}
              options={[
                { value: "below", label: "is below" },
                { value: "above", label: "is above" },
                { value: "between", label: "is between" },
              ]}
            />
            <div className="grid-2">
              <Field label={simple.compare === "between" ? `From (${unit})` : `Value (${unit})`}>
                <input className="input" type="number" step="any" required value={simple.value} onChange={(e) => update({ value: e.target.value })} />
              </Field>
              {simple.compare === "between" && (
                <Field label={`To (${unit})`}>
                  <input className="input" type="number" step="any" required value={simple.max} onChange={(e) => update({ max: e.target.value })} />
                </Field>
              )}
            </div>
            <label className="switch-row">
              <span>Only at certain times</span>
              <input type="checkbox" checked={simple.window} onChange={(e) => update({ window: e.target.checked })} />
            </label>
            {simple.window && timeInputs}
            </>
            )}
          </>
        ) : (
          <Field label="Condition (JSON)" hint="Supports threshold, range, time, all, any, not and always. See docs/rules.md.">
            <textarea className="input mono" rows={10} value={json} onChange={(e) => setJson(e.target.value)} style={{ padding: 12, fontSize: 13 }} />
          </Field>
        )}

        <Field label="then switch the relay">
          <Segmented<OnOff>
            label="Action"
            value={action}
            onChange={setAction}
            options={[
              { value: "on", label: "On" },
              { value: "off", label: "Off" },
            ]}
          />
        </Field>

        <Field label="Name (optional)">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder={advanced ? "" : describeCondition(fromSimple(simple))} />
        </Field>

        <details>
          <summary className="small muted" style={{ cursor: "pointer", minHeight: 32 }}>More options</summary>
          <div className="stack" style={{ gap: 14, marginTop: 10 }}>
            <div className="grid-2">
              <Field label="Priority" hint="Higher wins when rules disagree.">
                <input className="input" type="number" min={0} max={1000} value={priority} onChange={(e) => setPriority(e.target.value)} />
              </Field>
              <Field label="Cooldown (minutes)" hint="Minimum time before the rules switch it again.">
                <input className="input" type="number" min={0} max={1440} step="any" value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
              </Field>
            </div>
            <button
              type="button"
              className="btn small"
              onClick={() => {
                if (!advanced) setJson(JSON.stringify(fromSimple({ ...simple, sensor: simple.sensor || sensors[0] || "" }), null, 2));
                setAdvanced(!advanced);
              }}
              disabled={advanced && !toSimple(safeParse(json))}
            >
              {advanced ? "Back to simple editor" : "Edit as JSON (combine conditions)"}
            </button>
          </div>
        </details>

        {jsonError && <div className="notice error">{jsonError}</div>}
        <ErrorNote error={save.error} />
        <button type="submit" className="btn primary" disabled={save.isPending}>
          {rule ? "Save rule" : "Add rule"}
        </button>
      </form>
    </Dialog>
  );
}

function safeParse(text: string): Condition | undefined {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}
