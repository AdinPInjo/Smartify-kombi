// Sensors tab: what's connected to the Pi, and a wizard to add more.
// No sensors at all is fine too: then Smartify is for Victron and the heater.

import { ChevronLeft, ChevronRight, DoorOpen, Droplets, Loader2, MapPin, Pencil, Plus, RotateCw, Ruler, ScrollText, Stethoscope, Thermometer, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { PiHeader, type PinUse } from "@/components/PiHeader";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Dialog, ErrorNote, Field, Skeleton, useErrorToast, useToast } from "@/components/ui";
import { WaterCalibration } from "@/components/WaterCalibration";
import { CATALOG, CATEGORY_NAMES, catalogEntry, GPIO_TO_PIN, type Category, type CatalogEntry } from "@/lib/sensorCatalog";
import { useDebugMode, useSetDebugMode } from "@/lib/debug";

interface Sensor {
  id: string;
  name: string;
  kind: string;
  config: Record<string, unknown>;
  status: { ok: boolean | null; text: string; active?: boolean };
  needs_restart: boolean;
}

interface SensorsView {
  sensors: Sensor[];
  restart_required: boolean;
  pins: PinUse[];
  onewire_pin: number | null;
  available: boolean;
}

interface Discovered {
  onewire: { enabled: boolean; probes: string[] };
  i2c: { enabled: boolean; addresses: number[] };
}

const CATEGORY_ICON: Record<Category, ReactNode> = {
  climate: <Thermometer size={18} aria-hidden="true" />,
  position: <MapPin size={18} aria-hidden="true" />,
  water: <Droplets size={18} aria-hidden="true" />,
  security: <DoorOpen size={18} aria-hidden="true" />,
};

const hex = (n: number) => `0x${n.toString(16).padStart(2, "0")}`;

function useSensors(enabled: boolean) {
  return useQuery({
    queryKey: ["sensors"],
    queryFn: () => api.get<SensorsView>("/sensors"),
    refetchInterval: 4_000,
    enabled,
  });
}

export function Sensors() {
  const { cloud } = useMode();
  const sensors = useSensors(!cloud);
  const [wizard, setWizard] = useState<CatalogEntry | "choose" | null>(null);
  const [editing, setEditing] = useState<Sensor | null>(null);
  const [diagnosing, setDiagnosing] = useState<Sensor | null>(null);
  const [calibrating, setCalibrating] = useState(false);
  const data = sensors.data;

  return (
    <main className="page">
      <PageHeader
        kicker="Sensors"
        title="Sensors"
        sub="What's connected to the Pi. Only Victron and a diesel heater? Then you need none of these."
        right={
          !cloud && (
            <div className="row" style={{ gap: 6 }}>
              <Link to="/logs" className="btn small ghost">
                <ScrollText size={16} aria-hidden="true" /> Logs
              </Link>
              <button type="button" className="btn small primary" onClick={() => setWizard("choose")}>
                <Plus size={16} aria-hidden="true" /> Add sensor
              </button>
            </div>
          )
        }
      />
      {cloud && <Card><OnlyOnVan what="Adding sensors" /></Card>}
      {!cloud && sensors.isPending && <Skeleton height={200} />}
      {data?.restart_required && <RestartNotice />}
      {data && data.sensors.length === 0 && (
        <Card label="No sensors yet">
          <p className="small muted" style={{ margin: 0 }}>
            Smartify works without sensors: Victron devices, the diesel heater, switches and scenes don't need any. Add one when
            you have it: a temperature sensor for the cabin, a GPS for the map, the water tank's sender, a door contact.
          </p>
          <button type="button" className="btn primary" style={{ alignSelf: "flex-start" }} onClick={() => setWizard("choose")}>
            <Plus size={16} aria-hidden="true" /> Add the first sensor
          </button>
        </Card>
      )}
      {data && data.sensors.length > 0 && (
        <div className="grid">
          {(Object.keys(CATEGORY_NAMES) as Category[]).map((category) => {
            const list = data.sensors.filter((s) => catalogEntry(s.kind)?.category === category);
            if (list.length === 0) return null;
            return (
              <Card key={category} label={<span className="row" style={{ gap: 8 }}>{CATEGORY_ICON[category]} {CATEGORY_NAMES[category]}</span>}>
                <div className="list">
                  {list.map((sensor) => (
                    <SensorRow key={sensor.id} sensor={sensor} onEdit={() => setEditing(sensor)} onDiagnose={() => setDiagnosing(sensor)} onCalibrate={sensor.kind === "water_tank" ? () => setCalibrating(true) : undefined} />
                  ))}
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {data && (
        <Card label="GPIO pins">
          <span className="small muted">Which pins are taken. Hover or tap a pin to see what uses it.</span>
          <PiHeader pins={data.pins} />
        </Card>
      )}
      {wizard && data && (
        <SensorWizard
          start={wizard === "choose" ? null : wizard}
          view={data}
          onClose={() => setWizard(null)}
        />
      )}
      {editing && data && <EditDialog sensor={editing} view={data} onClose={() => setEditing(null)} />}
      {diagnosing && <DiagnoseDialog sensor={diagnosing} onClose={() => setDiagnosing(null)} />}
      {calibrating && (
        <Dialog title="Calibrate the water tank" onClose={() => setCalibrating(false)}>
          <WaterCalibration />
        </Dialog>
      )}
    </main>
  );
}

function SensorRow({
  sensor,
  onEdit,
  onDiagnose,
  onCalibrate,
}: {
  sensor: Sensor;
  onEdit: () => void;
  onDiagnose: () => void;
  onCalibrate?: () => void;
}) {
  const entry = catalogEntry(sensor.kind);
  const where =
    typeof sensor.config.pin === "number"
      ? `GPIO ${sensor.config.pin} (pin ${GPIO_TO_PIN[sensor.config.pin as number]})`
      : typeof sensor.config.address === "number"
        ? `I2C ${hex(sensor.config.address as number)}`
        : typeof sensor.config.rom === "string"
          ? `probe ${sensor.config.rom}`
          : typeof sensor.config.device === "string"
            ? String(sensor.config.device)
            : "";
  const dot = sensor.status.ok === true ? "ok" : sensor.status.ok === false ? "bad" : "warn";
  return (
    <div className="row-between" style={{ gap: 10, alignItems: "flex-start" }}>
      <span className="row" style={{ gap: 10, alignItems: "flex-start", minWidth: 0 }}>
        <span className={`dot ${dot}`} style={{ marginTop: 7 }} />
        <span className="stack" style={{ gap: 2, minWidth: 0 }}>
          <strong>{sensor.name}</strong>
          <span className="small">{sensor.status.text}</span>
          <span className="tiny faint">
            {entry?.name ?? sensor.kind}
            {where ? ` · ${where}` : ""}
          </span>
        </span>
      </span>
      <span className="row" style={{ gap: 2 }}>
        {onCalibrate && (
          <button type="button" className="btn small ghost" aria-label="Calibrate the water tank" title="Calibrate" onClick={onCalibrate}>
            <Ruler size={16} aria-hidden="true" />
          </button>
        )}
        <button type="button" className="btn small ghost" aria-label={`Diagnose ${sensor.name}`} title="Diagnose" onClick={onDiagnose}>
          <Stethoscope size={16} aria-hidden="true" />
        </button>
        <button type="button" className="btn small ghost" aria-label={`Edit ${sensor.name}`} title="Edit" onClick={onEdit}>
          <Pencil size={16} aria-hidden="true" />
        </button>
      </span>
    </div>
  );
}

interface Diagnostics {
  name: string;
  kind: string;
  status: Sensor["status"];
  hints: string[];
  reads?: number;
  good?: number;
  recent?: { time: number; temperature_c: number | null; humidity: number | null; error: string | null }[];
  changes?: { time: number; active: boolean }[];
}

function DiagnoseDialog({ sensor, onClose }: { sensor: Sensor; onClose: () => void }) {
  const diag = useQuery({
    queryKey: ["sensors", sensor.id, "diagnostics"],
    queryFn: () => api.get<Diagnostics>(`/sensors/${sensor.id}/diagnostics`),
    refetchInterval: 2_000,
  });
  const debug = useDebugMode();
  const setDebug = useSetDebugMode();
  const d = diag.data;
  const rate = d?.reads ? Math.round(((d.good ?? 0) / d.reads) * 100) : null;
  const time = (t: number) => new Date(t * 1000).toLocaleTimeString();
  return (
    <Dialog title={`Diagnose ${sensor.name}`} onClose={onClose}>
      <div className="stack" style={{ gap: 14 }}>
        <span className="small">
          Now: <strong>{d?.status.text ?? sensor.status.text}</strong>
        </span>
        {rate !== null && (
          <div className="stack" style={{ gap: 4 }}>
            <span className="small">
              Reads that worked (last hour): <strong>{rate} %</strong> <span className="muted">of {d?.reads}</span>
            </span>
            <div className="strength" style={{ width: "100%", height: 8 }} aria-hidden="true">
              <i style={{ width: `${rate}%`, background: rate >= 90 ? "var(--ok)" : rate >= 70 ? "var(--accent)" : "var(--alert)" }} />
            </div>
          </div>
        )}
        <div className="stack" style={{ gap: 6 }}>
          <span className="label">What to check</span>
          <ul className="guide-list small">
            {(d?.hints ?? ["Loading…"]).map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </div>
        {d?.recent && d.recent.length > 0 && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="label">Latest reads (newest first)</span>
            <div className="log-view mono tiny" style={{ maxHeight: 200 }}>
              {d.recent.map((r, i) => (
                <div key={i} className={`log-line ${r.error ? "warning" : ""}`}>
                  <span className="faint">{time(r.time)}</span>{" "}
                  {r.error
                    ? `failed: ${r.error}`
                    : `${r.temperature_c?.toFixed(1)} °C${r.humidity != null ? ` · ${r.humidity.toFixed(0)} %` : ""}`}
                </div>
              ))}
            </div>
          </div>
        )}
        {d?.changes && (
          <div className="stack" style={{ gap: 6 }}>
            <span className="label">Changes</span>
            {d.changes.length === 0 ? (
              <span className="small muted">None yet.</span>
            ) : (
              <div className="log-view mono tiny" style={{ maxHeight: 160 }}>
                {d.changes.map((c, i) => (
                  <div key={i} className="log-line">
                    <span className="faint">{time(c.time)}</span>{" "}
                    {sensor.kind === "door" ? (c.active ? "opened" : "closed") : c.active ? "motion" : "quiet"}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        <div className="row wrap" style={{ gap: 8 }}>
          {!debug.data?.enabled && (
            <button type="button" className="btn small" disabled={setDebug.isPending} onClick={() => setDebug.mutate({ enabled: true, hours: 2 })}>
              Turn on debug mode (2 h)
            </button>
          )}
          <Link to={`/logs?filter=${encodeURIComponent(sensor.name)}`} className="btn small ghost">
            <ScrollText size={16} aria-hidden="true" /> Log for {sensor.name}
          </Link>
        </div>
      </div>
    </Dialog>
  );
}

function RestartNotice() {
  const toast = useToast();
  const showError = useErrorToast();
  const restart = useMutation({
    mutationFn: () => api.post<{ restarting: boolean; message: string }>("/system/restart"),
    onSuccess: (r) => toast(r.message),
    onError: showError,
  });
  return (
    <div className="notice row-between wrap" style={{ gap: 10 }}>
      <span>GPS and water sender changes start working after Smartify restarts (about 20 seconds; switches are off meanwhile).</span>
      <button type="button" className="btn small primary" disabled={restart.isPending} onClick={() => restart.mutate()}>
        <RotateCw size={16} aria-hidden="true" /> Restart now
      </button>
    </div>
  );
}

// --- the wizard --------------------------------------------------------------------------------

type Step = "choose" | "wire" | "settings" | "test";
const STEPS: Step[] = ["choose", "wire", "settings", "test"];

function firstFreePin(pins: PinUse[], prefer: number[]): number | null {
  const free = new Set(pins.filter((p) => p.free).map((p) => p.gpio));
  return prefer.find((p) => free.has(p)) ?? pins.find((p) => p.free)?.gpio ?? null;
}

function SensorWizard({ start, view, onClose }: { start: CatalogEntry | null; view: SensorsView; onClose: () => void }) {
  const [entry, setEntry] = useState<CatalogEntry | null>(start);
  const [step, setStep] = useState<Step>(start ? "wire" : "choose");
  const [name, setName] = useState(start?.suggestedName ?? "");
  const [config, setConfig] = useState<Record<string, unknown>>({});
  const client = useQueryClient();
  const toast = useToast();
  const taken = new Set(view.sensors.map((s) => s.name));

  const pick = (chosen: CatalogEntry) => {
    setEntry(chosen);
    let suggestion = chosen.suggestedName;
    for (let i = 2; taken.has(suggestion); i++) suggestion = `${chosen.suggestedName}_${i}`;
    setName(suggestion);
    const pin = chosen.setting === "pin" ? firstFreePin(view.pins, [22, 27, 17, 23, 24, 5, 6]) : undefined;
    setConfig(
      chosen.setting === "pin"
        ? { pin }
        : chosen.setting === "address"
          ? { address: chosen.addresses?.[0] }
          : chosen.setting === "probe"
            ? { bus_pin: view.onewire_pin ?? 22 }
            : chosen.setting === "serial"
              ? { device: "/dev/serial0", baud: 9600 }
              : {},
    );
    setStep("wire");
  };

  const save = useMutation({
    mutationFn: () => api.post<Sensor>("/sensors", { name, kind: entry?.kind, config }),
    onSuccess: (sensor) => {
      void client.invalidateQueries({ queryKey: ["sensors"] });
      void client.invalidateQueries({ queryKey: ["climate"] });
      toast(sensor.needs_restart ? `${sensor.name} saved: restart to start it` : `${sensor.name} added`);
      onClose();
    },
  });

  const index = STEPS.indexOf(step);
  const title = entry ? `Add ${entry.name}` : "Add a sensor";
  const canNext =
    step === "choose"
      ? Boolean(entry)
      : step === "settings"
        ? /^[a-z0-9_]{1,24}$/.test(name) &&
          (entry?.setting !== "pin" || typeof config.pin === "number") &&
          (entry?.setting !== "probe" || typeof config.rom === "string")
        : true;

  return (
    <Dialog title={title} onClose={onClose}>
      <div className="guide-steps" aria-hidden="true">
        {STEPS.map((s, i) => (
          <span key={s} className={i <= index ? "done" : ""} />
        ))}
      </div>
      {step === "choose" && <ChooseStep view={view} onPick={pick} />}
      {step === "wire" && entry && <WireStep entry={entry} config={config} view={view} onPin={(pin) => setConfig({ ...config, pin })} />}
      {step === "settings" && entry && (
        <SettingsStep entry={entry} name={name} setName={setName} config={config} setConfig={setConfig} view={view} />
      )}
      {step === "test" && entry && <TestStep entry={entry} config={config} />}
      <ErrorNote error={save.error} />
      <div className="row-between">
        <button type="button" className="btn ghost" disabled={index === 0 || (step === "wire" && Boolean(start))} onClick={() => setStep(STEPS[index - 1])}>
          <ChevronLeft size={18} aria-hidden="true" /> Back
        </button>
        {step === "test" ? (
          <button type="button" className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Saving…" : "Save sensor"}
          </button>
        ) : step !== "choose" ? (
          <button type="button" className="btn primary" disabled={!canNext} onClick={() => setStep(STEPS[index + 1])}>
            Next <ChevronRight size={18} aria-hidden="true" />
          </button>
        ) : (
          <span />
        )}
      </div>
    </Dialog>
  );
}

function ChooseStep({ view, onPick }: { view: SensorsView; onPick: (entry: CatalogEntry) => void }) {
  return (
    <div className="stack" style={{ gap: 14 }}>
      <span className="small muted">Which sensor do you have? The name is usually printed on it or on the shop page.</span>
      {(Object.keys(CATEGORY_NAMES) as Category[]).map((category) => (
        <div key={category} className="stack" style={{ gap: 8 }}>
          <span className="label row" style={{ gap: 8 }}>{CATEGORY_ICON[category]} {CATEGORY_NAMES[category]}</span>
          <div className="catalog-grid">
            {CATALOG.filter((c) => c.category === category).map((entry) => {
              const already = entry.single && view.sensors.some((s) => s.kind === entry.kind);
              return (
                <button key={entry.kind} type="button" className="catalog-item" disabled={already} onClick={() => onPick(entry)}>
                  <strong>{entry.name}</strong>
                  <span className="tiny muted">{already ? "Already added (one per van)" : entry.short}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function WireStep({ entry, config, view, onPin }: { entry: CatalogEntry; config: Record<string, unknown>; view: SensorsView; onPin: (pin: number) => void }) {
  const dataGpio = entry.setting === "pin" ? (config.pin as number | null) : entry.setting === "probe" ? (config.bus_pin as number) : null;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <span className="small muted">
        Switch the Pi off before connecting wires (sudo shutdown now, then unplug). Then connect:
      </span>
      <ol className="guide-list">
        {entry.wiring.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ol>
      {entry.setting === "pin" && (
        <span className="small">
          Data wire on <strong>GPIO {String(config.pin ?? "–")}</strong>
          {typeof config.pin === "number" ? ` = physical pin ${GPIO_TO_PIN[config.pin]}` : ""}. Tap another free pin below to
          change it.
        </span>
      )}
      <PiHeader highlight={entry.pins} dataGpio={dataGpio} pins={view.pins} onPick={entry.setting === "pin" ? onPin : undefined} />
      {entry.note && <span className="tiny faint">{entry.note}</span>}
    </div>
  );
}

function SettingsStep({
  entry,
  name,
  setName,
  config,
  setConfig,
  view,
}: {
  entry: CatalogEntry;
  name: string;
  setName: (name: string) => void;
  config: Record<string, unknown>;
  setConfig: (config: Record<string, unknown>) => void;
  view: SensorsView;
}) {
  const scan = useQuery({
    queryKey: ["sensors", "discover"],
    queryFn: () => api.get<Discovered>("/sensors/discover"),
    enabled: entry.setting === "probe" || entry.setting === "address",
    refetchInterval: 5_000,
  });
  const used = new Set(view.sensors.map((s) => s.config.rom));
  const probes = (scan.data?.onewire.probes ?? []).filter((p) => !used.has(p));
  const busPin = Number(config.bus_pin ?? 22);
  return (
    <div className="stack" style={{ gap: 14 }}>
      <Field label="Name" hint="Lowercase, no spaces. Rules and alerts use it, e.g. inside, fridge, side_door.">
        <input className="input mono" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} maxLength={24} autoFocus />
      </Field>

      {entry.setting === "pin" && (
        <Field label="Data pin (GPIO)" hint="Free pins only. Same as tapping a pin in the previous step.">
          <select className="input" value={String(config.pin ?? "")} onChange={(e) => setConfig({ ...config, pin: Number(e.target.value) })}>
            {view.pins.filter((p) => p.free || p.gpio === config.pin).map((p) => (
              <option key={p.gpio} value={p.gpio}>
                GPIO {p.gpio} (pin {GPIO_TO_PIN[p.gpio]})
              </option>
            ))}
          </select>
        </Field>
      )}

      {entry.kind === "door" && (
        <Field label="The contact is closed (door shut) when…">
          <select className="input" value={String(config.closed_when ?? "low")} onChange={(e) => setConfig({ ...config, closed_when: e.target.value })}>
            <option value="low">it connects the pin to ground (most reed switches)</option>
            <option value="high">it opens the circuit (normally-open switch, inverted)</option>
          </select>
        </Field>
      )}

      {entry.setting === "address" && (
        <Field label="I2C address" hint={scan.data?.i2c.addresses.length ? `Found on the Pi now: ${scan.data.i2c.addresses.map(hex).join(", ")}` : "Searching the I2C bus…"}>
          <select className="input mono" value={String(config.address ?? "")} onChange={(e) => setConfig({ ...config, address: Number(e.target.value) })}>
            {entry.addresses?.map((a) => (
              <option key={a} value={a}>
                {hex(a)}
                {scan.data?.i2c.addresses.includes(a) ? "  ✓ found" : ""}
              </option>
            ))}
          </select>
        </Field>
      )}

      {entry.setting === "probe" &&
        (scan.data && !scan.data.onewire.enabled ? (
          <div className="notice stack" style={{ gap: 8 }}>
            <strong>Switch on the Pi's 1-Wire bus once</strong>
            <span className="small">
              Run this on the Pi (it restarts afterwards). It puts the bus on GPIO {busPin} (pin {GPIO_TO_PIN[busPin]}):
            </span>
            <code className="topic" style={{ fontSize: 12, textAlign: "left" }}>
              echo "dtoverlay=w1-gpio,gpiopin={busPin}" | sudo tee -a /boot/firmware/config.txt && sudo reboot
            </code>
            <span className="tiny faint">Then come back here: your probes appear in the list.</span>
          </div>
        ) : (
          <Field label="Which probe?" hint="Each probe has its own id. Warm one up in your hand to see which one it is.">
            <select className="input mono" value={String(config.rom ?? "")} onChange={(e) => setConfig({ ...config, rom: e.target.value })}>
              <option value="" disabled>
                {probes.length ? "Choose a probe" : scan.isPending ? "Looking for probes…" : "No new probes found (wiring? resistor?)"}
              </option>
              {probes.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </Field>
        ))}

      {entry.setting === "serial" && (
        <Field label="Serial port" hint="Leave as it is for a GPS on the header pins. USB GPS: /dev/ttyACM0 or /dev/ttyUSB0.">
          <input className="input mono" value={String(config.device ?? "")} onChange={(e) => setConfig({ ...config, device: e.target.value })} />
        </Field>
      )}
      {entry.kind === "water_tank" && (
        <span className="small muted">Nothing to set here. After saving and restarting, calibrate it here in the Sensors tab (the ruler icon).</span>
      )}
    </div>
  );
}

function TestStep({ entry, config }: { entry: CatalogEntry; config: Record<string, unknown> }) {
  const test = useMutation({
    mutationFn: () => api.post<{ ok: boolean; text: string }>("/sensors/test", { kind: entry.kind, config }),
  });
  const { mutate } = test;
  useEffect(() => {
    mutate();
  }, [mutate]);
  return (
    <div className="stack" style={{ gap: 12 }}>
      <span className="small muted">
        {entry.kind === "door"
          ? "Open and close the door, then test again: the reading should change."
          : entry.kind === "motion"
            ? "Wave in front of the sensor, then test again (PIRs need up to a minute to settle after power-up)."
            : "One live reading, to check the wiring before saving."}
      </span>
      <div className={`notice ${test.data?.ok ? "ok" : test.data ? "error" : ""} row`} style={{ gap: 10 }} role="status">
        {test.isPending ? <Loader2 size={18} className="spin" aria-hidden="true" /> : null}
        <span>
          {test.isPending
            ? "Reading…"
            : test.data
              ? test.data.ok
                ? `Works: ${test.data.text}`
                : `Not yet: ${test.data.text}`
              : test.error
                ? String(test.error)
                : ""}
        </span>
      </div>
      <button type="button" className="btn small" style={{ alignSelf: "flex-start" }} disabled={test.isPending} onClick={() => mutate()}>
        <RotateCw size={16} aria-hidden="true" /> Test again
      </button>
      {test.data && !test.data.ok && (
        <span className="tiny faint">You can save anyway and fix the wiring later; the sensor then shows what's wrong.</span>
      )}
    </div>
  );
}

// --- edit --------------------------------------------------------------------------------------

function EditDialog({ sensor, view, onClose }: { sensor: Sensor; view: SensorsView; onClose: () => void }) {
  const entry = catalogEntry(sensor.kind);
  const client = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(sensor.name);
  const [pin, setPin] = useState(sensor.config.pin as number | undefined);
  const done = (message: string) => {
    void client.invalidateQueries({ queryKey: ["sensors"] });
    void client.invalidateQueries({ queryKey: ["climate"] });
    toast(message);
    onClose();
  };
  const save = useMutation({
    mutationFn: () => api.patch(`/sensors/${sensor.id}`, { name, config: pin !== undefined ? { pin } : {} }),
    onSuccess: () => done("Saved"),
  });
  const remove = useMutation({
    mutationFn: () => api.delete(`/sensors/${sensor.id}`),
    onSuccess: () => done(`${sensor.name} removed`),
  });
  return (
    <Dialog title={`Edit ${sensor.name}`} onClose={onClose}>
      <div className="stack" style={{ gap: 14 }}>
        <span className="small muted">{entry?.name}</span>
        <Field label="Name" hint="Rules and alerts that use the old name need to be changed too.">
          <input className="input mono" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} maxLength={24} />
        </Field>
        {pin !== undefined && (
          <Field label="Data pin (GPIO)">
            <select className="input" value={String(pin)} onChange={(e) => setPin(Number(e.target.value))}>
              {view.pins.filter((p) => p.free || p.gpio === sensor.config.pin).map((p) => (
                <option key={p.gpio} value={p.gpio}>
                  GPIO {p.gpio} (pin {GPIO_TO_PIN[p.gpio]})
                </option>
              ))}
            </select>
          </Field>
        )}
        <ErrorNote error={save.error ?? remove.error} />
        <div className="row-between">
          <button
            type="button"
            className="btn small danger"
            disabled={remove.isPending}
            onClick={() => window.confirm(`Remove ${sensor.name}? Its history stays.`) && remove.mutate()}
          >
            <Trash2 size={16} aria-hidden="true" /> Remove
          </button>
          <button type="button" className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>
            Save
          </button>
        </div>
      </div>
    </Dialog>
  );
}
