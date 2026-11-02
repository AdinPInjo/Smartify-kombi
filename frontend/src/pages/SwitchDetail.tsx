import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useClimate, useDeleteRelay, useDeleteRule, useRelay, useRelayEvents, useRules, useSaveRule, useUpdateRelay } from "@/api/hooks";
import type { Relay, Rule } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { RelayControl, relayTitle } from "@/components/RelayControl";
import { describeCondition, RuleEditor } from "@/components/RuleEditor";
import { Card, ErrorNote, Field, Skeleton, useErrorToast, useToast } from "@/components/ui";
import { ago, dateTime, duration, humanize } from "@/lib/format";

export function SwitchDetail() {
  const { id = "" } = useParams();
  const relay = useRelay(id);

  if (relay.isPending) {
    return (
      <main className="page">
        <Skeleton height={40} width={200} />
        <Skeleton height={200} />
      </main>
    );
  }
  if (!relay.data) {
    return (
      <main className="page">
        <ErrorNote error={relay.error ?? "Relay not found"} />
        <Link to="/switches">Back to switches</Link>
      </main>
    );
  }
  const r = relay.data;
  return (
    <main className="page">
      <PageHeader kicker="Switch" title={relayTitle(r)} sub={`GPIO ${r.gpio_pin}${r.active_low ? " · active-low" : ""} · rule name “${r.name}”`} />
      <div className="grid">
        <div className="stack" style={{ gap: "var(--gap)" }}>
          <RelayControl relay={r} large link={false} />
          <Rules relay={r} />
        </div>
        <div className="stack" style={{ gap: "var(--gap)" }}>
          <RelaySettings relay={r} />
          <Events relay={r} />
        </div>
      </div>
    </main>
  );
}

function Rules({ relay }: { relay: Relay }) {
  const rules = useRules(relay.id);
  const save = useSaveRule(relay.id);
  const remove = useDeleteRule(relay.id);
  const showError = useErrorToast();
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const data = rules.data;

  return (
    <Card label="Automatic rules" action={<button type="button" className="btn small" onClick={() => setEditing("new")}>Add rule</button>}>
      {data && (
        <div className={`small ${relay.mode === "manual" ? "c-accent" : "muted"}`}>
          {relay.mode === "manual"
            ? "Manual override active: rules are paused until it ends or you switch to Auto."
            : `Now: ${data.decision.state ? `wants ${data.decision.state.toUpperCase()}` : "keeping current state"} · ${data.decision.reason}`}
        </div>
      )}
      {rules.isPending && <Skeleton height={80} />}
      {data?.rules.length === 0 && (
        <p className="muted small" style={{ margin: 0 }}>
          No rules: in Auto mode this relay stays off. Add one, e.g. “Heat below 8 °C”.
        </p>
      )}
      <div className="list">
        {data?.rules.map((rule) => (
          <div key={rule.id} className="stack" style={{ gap: 6, opacity: rule.enabled ? 1 : 0.55 }}>
            <div className="row-between">
              <span className="row">
                <span className={`dot ${rule.status?.is_winner ? "on" : rule.status?.matched ? "warn" : "off"}`} />
                <strong>{rule.name}</strong>
              </span>
              <span className={`mono tiny ${rule.action === "on" ? "c-accent" : "muted"}`}>→ {rule.action.toUpperCase()}</span>
            </div>
            <span className="small muted">
              {describeCondition(rule.condition)} · priority {rule.priority}
              {rule.cooldown_seconds ? ` · cooldown ${duration(rule.cooldown_seconds)}` : ""}
            </span>
            {rule.status && (
              <span className={`tiny ${rule.status.issue ? "c-accent" : "muted"}`}>
                {rule.status.issue
                  ? `Sensor ${humanize(rule.status.issue).toLowerCase()}`
                  : `${rule.status.matched ? "Matches now" : "Not matching"}${
                      Object.keys(rule.status.values).length
                        ? ` (${Object.entries(rule.status.values).map(([k, v]) => `${k} ${v}`).join(", ")})`
                        : ""
                    }${rule.status.is_winner ? " · in control" : ""}`}
              </span>
            )}
            <div className="row wrap">
              <button type="button" className="btn small" onClick={() => setEditing(rule)}>Edit</button>
              <button
                type="button"
                className="btn small"
                onClick={() => save.mutate({ id: rule.id, rule: { enabled: !rule.enabled } }, { onError: showError })}
              >
                {rule.enabled ? "Disable" : "Enable"}
              </button>
              <button
                type="button"
                className="btn small danger"
                onClick={() => window.confirm(`Delete rule “${rule.name}”?`) && remove.mutate(rule.id, { onError: showError })}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
      {editing && <RuleEditor relayId={relay.id} rule={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function RelaySettings({ relay }: { relay: Relay }) {
  const update = useUpdateRelay();
  const remove = useDeleteRelay();
  const climate = useClimate();
  const toast = useToast();
  const navigate = useNavigate();
  const [form, setForm] = useState(() => toForm(relay));
  useEffect(() => setForm(toForm(relay)), [relay.revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (changes: Partial<ReturnType<typeof toForm>>) => setForm((f) => ({ ...f, ...changes }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const cutoff = form.cutoffEnabled && form.cutoffSensor;
    update.mutate(
      {
        id: relay.id,
        changes: {
          label: form.label.trim() || null,
          gpio_pin: Number(form.pin),
          active_low: form.activeLow,
          enabled: form.enabled,
          min_on_seconds: Math.round(Number(form.minOn) * 60),
          min_off_seconds: Math.round(Number(form.minOff) * 60),
          cutoff_sensor: cutoff ? form.cutoffSensor : null,
          cutoff_max_c: cutoff ? Number(form.cutoffMax) : null,
        },
      },
      { onSuccess: () => toast("Settings saved") },
    );
  };

  return (
    <Card label="Settings">
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <Field label="Label">
          <input className="input" value={form.label} onChange={(e) => set({ label: e.target.value })} maxLength={60} placeholder={relay.name} />
        </Field>
        <div className="grid-2">
          <Field label="GPIO pin (BCM)">
            <input className="input" type="number" min={0} max={27} value={form.pin} onChange={(e) => set({ pin: e.target.value })} required />
          </Field>
          <label className="switch-row" style={{ alignSelf: "end" }}>
            <span>Active-low board</span>
            <input type="checkbox" checked={form.activeLow} onChange={(e) => set({ activeLow: e.target.checked })} />
          </label>
        </div>
        <p className="tiny muted" style={{ margin: 0 }}>
          If the relay clicks on while the dashboard says OFF, your board is active-low: tick the box.
        </p>
        <div className="grid-2">
          <Field label="Minimum on time (min)">
            <input className="input" type="number" min={0} step="any" value={form.minOn} onChange={(e) => set({ minOn: e.target.value })} />
          </Field>
          <Field label="Minimum off time (min)">
            <input className="input" type="number" min={0} step="any" value={form.minOff} onChange={(e) => set({ minOff: e.target.value })} />
          </Field>
        </div>

        <div className="tile" style={{ gap: 10 }}>
          <label className="switch-row">
            <span>
              <strong>Safety cutoff</strong>
              <br />
              <span className="small muted">Forces the relay off above a temperature, even in manual mode.</span>
            </span>
            <input type="checkbox" checked={form.cutoffEnabled} onChange={(e) => set({ cutoffEnabled: e.target.checked })} />
          </label>
          {form.cutoffEnabled && (
            <div className="grid-2">
              <Field label="Sensor">
                <select className="input" value={form.cutoffSensor} onChange={(e) => set({ cutoffSensor: e.target.value })}>
                  {climate.data?.map((s) => (
                    <option key={s.sensor} value={s.sensor}>
                      {s.sensor}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Off above (°C)">
                <input className="input" type="number" min={-40} max={80} step="any" value={form.cutoffMax} onChange={(e) => set({ cutoffMax: e.target.value })} required />
              </Field>
            </div>
          )}
        </div>

        <label className="switch-row">
          <span>Enabled (disabled relays stay off)</span>
          <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
        </label>
        <ErrorNote error={update.error} />
        <button type="submit" className="btn primary" disabled={update.isPending}>
          Save settings
        </button>
        <button
          type="button"
          className="btn danger"
          onClick={() =>
            window.confirm(`Delete ${relayTitle(relay)} and its rules?`) &&
            remove.mutate(relay.id, { onSuccess: () => navigate("/switches") })
          }
        >
          Delete relay
        </button>
        <ErrorNote error={remove.error} />
      </form>
    </Card>
  );

  function toForm(r: Relay) {
    return {
      label: r.label ?? "",
      pin: String(r.gpio_pin),
      activeLow: r.active_low,
      enabled: r.enabled,
      minOn: String(r.min_on_seconds / 60),
      minOff: String(r.min_off_seconds / 60),
      cutoffEnabled: r.cutoff_sensor !== null,
      cutoffSensor: r.cutoff_sensor ?? climate.data?.[0]?.sensor ?? "",
      cutoffMax: r.cutoff_max_c !== null ? String(r.cutoff_max_c) : "30",
    };
  }
}

function Events({ relay }: { relay: Relay }) {
  const events = useRelayEvents(relay.id);
  return (
    <Card label="Recent changes">
      {events.isPending && <Skeleton height={80} />}
      {events.data?.length === 0 && <p className="muted small">Nothing yet.</p>}
      <div className="table-wrap">
        <table>
          <tbody>
            {events.data?.map((event) => (
              <tr key={event.id}>
                <td className="mono tiny" style={{ whiteSpace: "nowrap" }} title={ago(event.created_at)}>
                  {dateTime(event.created_at)}
                </td>
                <td className={event.new_state === "on" ? "c-accent" : "muted"}>{event.new_state.toUpperCase()}</td>
                <td className="small">
                  {humanize(event.source)}
                  {event.reason ? ` · ${event.reason}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
