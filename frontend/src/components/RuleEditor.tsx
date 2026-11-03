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

interface SimpleRule {
  metric: Metric;
  sensor: string;
  compare: Compare;
  value: string;
  max: string;
}

/** Rules made in this editor are one comparison; anything else is edited as JSON. */
function toSimple(condition: Condition | undefined): SimpleRule | null {
  if (!condition) return null;
  if (condition.type === "threshold") {
    return {
      metric: condition.metric,
      sensor: condition.sensor,
      compare: condition.op.startsWith("<") ? "below" : "above",
      value: String(condition.value),
      max: "",
    };
  }
  if (condition.type === "range") {
    return { metric: condition.metric, sensor: condition.sensor, compare: "between", value: String(condition.min), max: String(condition.max) };
  }
  return null;
}

function fromSimple(rule: SimpleRule): Condition {
  if (rule.compare === "between") {
    return { type: "range", metric: rule.metric, sensor: rule.sensor, min: Number(rule.value), max: Number(rule.max) };
  }
  return { type: "threshold", metric: rule.metric, sensor: rule.sensor, op: rule.compare === "below" ? "<" : ">", value: Number(rule.value) };
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
    initial ?? { metric: "temperature", sensor: climate.data?.[0]?.sensor ?? "", compare: "below", value: "8", max: "" },
  );
  const [json, setJson] = useState(JSON.stringify(rule?.condition ?? fromSimple(simple), null, 2));
  const [priority, setPriority] = useState(String(rule?.priority ?? 100));
  const [cooldown, setCooldown] = useState(String(Math.round((rule?.cooldown_seconds ?? 60) / 60)));
  const [jsonError, setJsonError] = useState<string | null>(null);

  const sensors = useMemo(() => {
    if (simple.metric === "temperature" || simple.metric === "humidity") return climate.data?.map((s) => s.sensor) ?? [];
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

  const unit = METRIC_UNITS[simple.metric];

  return (
    <Dialog title={rule ? "Edit rule" : "New rule"} onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        {!advanced ? (
          <>
            <div className="grid-2">
              <Field label="When">
                <select className="input" value={simple.metric} onChange={(e) => update({ metric: e.target.value as Metric, sensor: "" })}>
                  {Object.entries(METRIC_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
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
            </div>
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
          </>
        ) : (
          <Field label="Condition (JSON)" hint="Supports threshold, range, all, any, not and always. See docs/rules.md.">
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
