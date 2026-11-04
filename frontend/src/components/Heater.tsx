// Diesel heaters over Bluetooth: status and real controls (on/off, temperature
// or power level). Off always lets the heater cool down by itself.

import { AlertTriangle, Flame, Minus, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import { Num, Segmented, useErrorToast, useToast } from "./ui";
import { ago, fmt } from "@/lib/format";

export interface HeaterStatus {
  running: boolean;
  phase: string;
  phase_name: string;
  mode: "temperature" | "level" | null;
  target_temperature: number | null;
  level: number | null;
  cabin_temperature: number | null;
  heater_temperature: number | null;
  voltage: number | null;
  error_code: number | null;
  error: string | null;
  co_ppm: number | null;
  protocol: string | null;
  updated_at: number;
}

export interface Heater {
  id: string;
  name: string;
  mac: string;
  connected: boolean;
  error: string | null;
  last_seen: number | null;
  status: HeaterStatus | null;
  pending?: boolean;
}

export const useHeaters = () =>
  useQuery({
    queryKey: ["heaters"],
    queryFn: () => api.get<{ heaters: Heater[]; available: boolean }>("/heaters"),
    refetchInterval: 5_000,
  });

function useHeaterControl(heater: Heater) {
  const client = useQueryClient();
  const toast = useToast();
  const showError = useErrorToast();
  const { cloud } = useMode();
  const done = () => {
    void client.invalidateQueries({ queryKey: ["heaters"] });
    if (cloud) toast("Sent to the van");
  };
  const power = useMutation({
    mutationFn: (on: boolean) => api.post<Heater>(`/heaters/${heater.id}/power`, { on }),
    onSuccess: done,
    onError: showError,
  });
  const settings = useMutation({
    mutationFn: (body: { mode?: string; temperature?: number; level?: number }) =>
      api.post<Heater>(`/heaters/${heater.id}/settings`, body),
    onSuccess: done,
    onError: showError,
  });
  return { power, settings, busy: power.isPending || settings.isPending };
}

const PHASE_CLASS: Record<string, string> = {
  running: "ok",
  ignition: "warn",
  self_test: "warn",
  cooldown: "warn",
  fault: "bad",
};

function Stepper({
  label,
  value,
  unit,
  min,
  max,
  disabled,
  onChange,
}: {
  label: string;
  value: number | null;
  unit: string;
  min: number;
  max: number;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  const current = value ?? Math.round((min + max) / 2);
  return (
    <div className="stepper" role="group" aria-label={label}>
      <button type="button" className="dash-icon" aria-label={`${label} down`} disabled={disabled || current <= min} onClick={() => onChange(current - 1)}>
        <Minus size={18} aria-hidden="true" />
      </button>
      <span className="num stepper-value">
        {value ?? "–"}
        <span className="muted" style={{ fontSize: "0.5em", marginLeft: 2 }}>{unit}</span>
      </span>
      <button type="button" className="dash-icon" aria-label={`${label} up`} disabled={disabled || current >= max} onClick={() => onChange(current + 1)}>
        <Plus size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

export function HeaterControl({ heater, large = false }: { heater: Heater; large?: boolean }) {
  const { power, settings, busy } = useHeaterControl(heater);
  const s = heater.status;
  const usable = heater.connected && Boolean(s);
  const mode = s?.mode ?? "temperature";
  return (
    <div className="stack" style={{ gap: large ? 16 : 12 }}>
      <div className="row-between">
        <span className="row" style={{ gap: 8 }}>
          <Flame size={large ? 22 : 18} aria-hidden="true" className={s?.running ? "c-accent" : "muted"} />
          <strong style={{ fontSize: large ? 20 : 16 }}>{heater.name}</strong>
        </span>
        <span className="chip">
          <span className={`dot ${heater.connected ? PHASE_CLASS[s?.phase ?? ""] ?? "" : "bad"}`} />
          {heater.connected ? (s?.phase_name ?? "connecting") : "not connected"}
        </span>
      </div>

      {s?.error && (
        <div className="notice error row" style={{ gap: 8 }} role="alert">
          <AlertTriangle size={18} aria-hidden="true" /> {s.error}
        </div>
      )}
      {!heater.connected && (
        <span className="small muted">
          {heater.error ?? "Connecting…"}
          {heater.last_seen ? ` · last contact ${ago(heater.last_seen)}` : ""}
        </span>
      )}

      {s && (
        <div className="row wrap" style={{ gap: large ? 28 : 18 }}>
          <div className="stack" style={{ gap: 0 }}>
            <Num value={fmt(s.cabin_temperature, 0)} unit="°C" size={large ? "l" : "m"} />
            <span className="tiny muted">at the heater</span>
          </div>
          <div className="stack" style={{ gap: 0 }}>
            <Num value={fmt(s.heater_temperature, 0)} unit="°C" size={large ? "l" : "m"} />
            <span className="tiny muted">burner</span>
          </div>
          <div className="stack" style={{ gap: 0 }}>
            <Num value={fmt(s.voltage, 1)} unit="V" size={large ? "l" : "m"} />
            <span className="tiny muted">supply</span>
          </div>
        </div>
      )}

      <div className="heater-power">
        <button
          type="button"
          className={`btn ${s?.running ? "" : "primary"}`}
          disabled={!usable || busy || !s?.running}
          onClick={() => power.mutate(false)}
        >
          Off
        </button>
        <button
          type="button"
          className={`btn ${s?.running ? "primary" : ""}`}
          disabled={!usable || busy || Boolean(s?.running)}
          onClick={() => power.mutate(true)}
        >
          On
        </button>
      </div>

      <Segmented<"temperature" | "level">
        label="Heater mode"
        value={mode}
        disabled={!usable || busy}
        onChange={(value) => settings.mutate({ mode: value })}
        options={[
          { value: "temperature", label: "Temperature" },
          { value: "level", label: "Power level" },
        ]}
      />
      {mode === "temperature" ? (
        <Stepper label="Target temperature" value={s?.target_temperature ?? null} unit="°C" min={8} max={36} disabled={!usable || busy}
          onChange={(temperature) => settings.mutate({ temperature })} />
      ) : (
        <Stepper label="Power level" value={s?.level ?? null} unit="/10" min={1} max={10} disabled={!usable || busy}
          onChange={(level) => settings.mutate({ level })} />
      )}
      {s?.phase === "cooldown" && <span className="tiny faint">Cooling down: the fan runs until the burner is cold. That's normal.</span>}
    </div>
  );
}

/** Every heater, for the overview, the tablet panel and the climate page. */
export function HeaterCards({ large = false }: { large?: boolean }) {
  const heaters = useHeaters();
  const { cloud } = useMode();
  const list = heaters.data?.heaters ?? [];
  if (heaters.data && list.length === 0) {
    return (
      <p className="small muted" style={{ margin: 0 }}>
        No diesel heater yet.{" "}
        {cloud ? "Add it on the van's own dashboard." : <Link to="/climate/heaters">Add one over Bluetooth ›</Link>}
      </p>
    );
  }
  return (
    <div className="stack" style={{ gap: 20 }}>
      {list.map((heater) => (
        <HeaterControl key={heater.id} heater={heater} large={large} />
      ))}
    </div>
  );
}
