import { Bluetooth, CheckCircle2, Loader2, Radio } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAddVictron, useMode, useRemoveVictron, useVictronDevices, useVictronNearby } from "@/api/hooks";
import type { VictronConfigured, VictronNearby } from "@/api/types";
import { PageHeader } from "@/components/PageHeader";
import { SetupGuide, type GuideStep } from "@/components/SetupGuide";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Dialog, ErrorNote, Field, Skeleton, useErrorToast, useToast } from "@/components/ui";
import { ago } from "@/lib/format";

export const KIND_LABELS: Record<string, string> = {
  battery_monitor: "Battery monitor (SmartShunt, BMV)",
  solar_charger: "Solar charger (SmartSolar MPPT)",
  dcdc_converter: "DC-DC charger (Orion)",
  inverter_charger: "Inverter / charger (MultiPlus, via VE.Bus Smart dongle)",
};

const KEY = /^[0-9a-f]{32}$/;

function signal(rssi: number | null): string {
  if (rssi === null) return "";
  if (rssi > -65) return "strong signal";
  if (rssi > -80) return "good signal";
  return "weak signal";
}

export function VictronSetup() {
  const { cloud } = useMode();
  const devices = useVictronDevices(!cloud);
  const [adding, setAdding] = useState<VictronNearby | "manual" | null>(null);
  const [added, setAdded] = useState<{ name: string; checked: boolean } | null>(null);
  const data = devices.data;

  return (
    <main className="page">
      <PageHeader
        kicker="Energy"
        title="Victron devices"
        sub="Read over Bluetooth with Victron's “Instant Readout”. Nothing on your devices is ever changed."
        right={
          <Link to="/energy" className="btn small ghost">
            ← Energy
          </Link>
        }
      />
      {cloud && (
        <Card label="Victron devices">
          <OnlyOnVan what="Adding Victron devices" />
        </Card>
      )}
      {!cloud && devices.isPending && <Skeleton height={200} />}
      {data && (
        <>
          {data.error && <div className="notice error">{data.error}</div>}
          <SetupGuide id="victron" title="Add a Victron device" steps={VICTRON_GUIDE} startOpen={data.devices.length === 0} />
          {added && <AddedNotice name={added.name} checked={added.checked} onClose={() => setAdded(null)} />}
          <div className="grid">
            <div className="stack" style={{ gap: "var(--gap)" }}>
              <YourDevices devices={data.devices} />
            </div>
            <Nearby onPick={setAdding} enabled={data.bluetooth} />
          </div>
        </>
      )}
      {adding && (
        <AddDialog
          device={adding === "manual" ? null : adding}
          onClose={() => setAdding(null)}
          onAdded={(name, checked) => {
            setAdding(null);
            setAdded({ name, checked });
          }}
        />
      )}
    </main>
  );
}

function AddedNotice({ name, checked, onClose }: { name: string; checked: boolean; onClose: () => void }) {
  return (
    <div className={`notice ${checked ? "ok" : ""} row-between wrap`}>
      <span className="row" style={{ gap: 8 }}>
        <CheckCircle2 size={18} aria-hidden="true" />
        {checked
          ? `“${name}” is connected. Its values appear on the Energy page within a few seconds.`
          : `“${name}” is saved. It hasn't been heard yet: check it is in range and Instant Readout is on.`}
      </span>
      <span className="row" style={{ gap: 8 }}>
        <Link to="/energy" className="btn small">
          Open Energy
        </Link>
        <button type="button" className="btn small ghost" onClick={onClose}>
          Close
        </button>
      </span>
    </div>
  );
}

function statusLabel(device: VictronConfigured): { dot: string; text: string } {
  if (device.status === "ok") return { dot: "ok", text: `receiving · ${signal(device.rssi)}` };
  if (device.status === "stale") return { dot: "warn", text: `no data since ${ago(device.updated_at)}` };
  return { dot: "off", text: "not heard yet (in range? Instant Readout on? right key?)" };
}

function YourDevices({ devices }: { devices: VictronConfigured[] }) {
  const remove = useRemoveVictron();
  const showError = useErrorToast();
  const toast = useToast();
  return (
    <Card label="Your devices">
      {devices.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>
          None yet. Pick yours from the list of devices nearby to add it.
        </p>
      ) : (
        <div className="list">
          {devices.map((device) => {
            const status = statusLabel(device);
            return (
              <div key={device.name} className="row-between" style={{ gap: 12, alignItems: "flex-start" }}>
                <span className="row" style={{ gap: 10, alignItems: "flex-start", minWidth: 0 }}>
                  <span className={`dot ${status.dot}`} style={{ marginTop: 6 }} />
                  <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                    <strong>{device.name}</strong>
                    <span className="small muted">
                      {device.model ?? (device.kind ? KIND_LABELS[device.kind] ?? device.kind : device.mac)}
                    </span>
                    <span className="tiny faint">{status.text}</span>
                  </span>
                </span>
                {device.source === "env" ? (
                  <span className="tiny faint" style={{ whiteSpace: "nowrap" }}>set in .env</span>
                ) : (
                  <button
                    type="button"
                    className="btn small ghost"
                    disabled={remove.isPending}
                    onClick={() => {
                      if (!window.confirm(`Remove ${device.name}? Rules that use it will switch their relay off.`)) return;
                      remove.mutate(device.name, { onSuccess: () => toast(`${device.name} removed`), onError: showError });
                    }}
                  >
                    Remove
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
      <span className="tiny faint">
        The name (e.g. <code>shunt</code>) is what rules use, like “heater off when shunt battery below 20 %”.
      </span>
    </Card>
  );
}

const VICTRON_GUIDE: GuideStep[] = [
  {
    title: "What you need",
    body: (
      <>
        <p style={{ margin: 0 }}>
          Smartify reads your Victron devices over Bluetooth, the same way the VictronConnect app does. Nothing on them is
          ever changed. You need:
        </p>
        <ul className="guide-list">
          <li>
            The free <strong>VictronConnect</strong> app on your phone (App Store or Google Play).
          </li>
          <li>Your phone and the Pi near the van, with the Victron devices switched on.</li>
          <li>About 2 minutes per device.</li>
        </ul>
        <p className="small muted" style={{ margin: 0 }}>
          Works with SmartShunt and BMV-712 (battery), SmartSolar MPPT (solar), Orion Smart / Orion XS (charging while
          driving) and MultiPlus or Quattro with the VE.Bus Smart dongle.
        </p>
      </>
    ),
  },
  {
    title: "Switch on “Instant readout”",
    body: (
      <>
        <p style={{ margin: 0 }}>Do this once for each device, in VictronConnect:</p>
        <ol className="guide-list">
          <li>Tap the device in the list to open it.</li>
          <li>
            Tap the <strong>⚙ gear</strong> at the top right.
          </li>
          <li>
            Tap the <strong>⋮ menu</strong> (top right) and choose <strong>Product info</strong>.
          </li>
          <li>
            Scroll down to <strong>Instant readout via Bluetooth</strong> and set it to <strong>Enabled</strong>.
          </li>
        </ol>
      </>
    ),
    trouble: (
      <>
        <span>
          <strong>No “Instant readout” on that screen?</strong> The device needs newer firmware. VictronConnect offers the
          update when you open the device; let it install, then look again.
        </span>
        <span>
          <strong>MultiPlus or Quattro?</strong> They need the VE.Bus Smart dongle; set it up in VictronConnect first.
        </span>
      </>
    ),
  },
  {
    title: "Copy the encryption key",
    body: (
      <>
        <p style={{ margin: 0 }}>
          On the same Product info screen, next to <strong>Instant readout details</strong>, tap <strong>Show</strong>.
        </p>
        <p style={{ margin: 0 }}>
          You see an <strong>encryption key</strong>: 32 characters of numbers and the letters a–f, like{" "}
          <code>0df4d0395b7d1a876c0c33ecb9e70dcd</code>. Tap it to copy it.
        </p>
        <p className="small muted" style={{ margin: 0 }}>
          Using another device for Smartify? Send the key to yourself (notes, message) and copy it there. The key only
          lets someone <em>read</em> the values; it can't change anything.
        </p>
      </>
    ),
  },
  {
    title: "Add it here",
    body: (
      <>
        <p style={{ margin: 0 }}>
          In <strong>Devices nearby</strong> on this page, your device shows up within a few seconds, with its name. Tap{" "}
          <strong>Add</strong>, paste the key and save.
        </p>
        <p style={{ margin: 0 }}>Smartify checks the key right away and tells you if it doesn't fit.</p>
      </>
    ),
    trouble: (
      <>
        <span>
          <strong>Not in the list?</strong> Move closer: Bluetooth reaches about 10 metres, less through metal walls. Check
          that Instant readout is on (step 2).
        </span>
        <span>
          <strong>“Wrong key”?</strong> Copy it again from VictronConnect; one wrong character is enough.
        </span>
        <span>
          <strong>“Bluetooth is off” at the top of this page?</strong> The message there says how to switch it on.
        </span>
      </>
    ),
  },
  {
    title: "Done: do the next one",
    body: (
      <>
        <p style={{ margin: 0 }}>
          The values appear on the <strong>Energy</strong> page and the overview within seconds: battery %, solar watts,
          charging while driving, inverter.
        </p>
        <p style={{ margin: 0 }}>
          Repeat steps 2 to 4 for each of your Victron devices. Then you can use them in rules, e.g. switch the fridge off
          when the battery drops below 30 %.
        </p>
      </>
    ),
  },
];

function Nearby({ onPick, enabled }: { onPick: (device: VictronNearby | "manual") => void; enabled: boolean }) {
  const nearby = useVictronNearby(enabled);
  const list = nearby.data?.devices ?? [];
  return (
    <Card
      label={
        <span className="row" style={{ gap: 8 }}>
          <Radio size={16} aria-hidden="true" /> Devices nearby
        </span>
      }
      action={
        enabled && (
          <span className="row tiny faint" style={{ gap: 6 }}>
            <Loader2 size={13} className="spin" aria-hidden="true" /> searching
          </span>
        )
      }
    >
      {!enabled ? (
        <p className="small muted" style={{ margin: 0 }}>
          Bluetooth isn't available on this Pi, so devices can't be found.
        </p>
      ) : list.length === 0 ? (
        <div className="stack" style={{ gap: 8 }}>
          <span className="row small muted" style={{ gap: 8 }}>
            <Bluetooth size={16} aria-hidden="true" /> Looking for Victron devices…
          </span>
          <span className="tiny faint">
            Devices show up a few seconds after Instant Readout is enabled. They need to be within about 10 m of the Pi.
          </span>
        </div>
      ) : (
        <div className="list">
          {list.map((device) => (
            <div key={device.mac} className="row-between" style={{ gap: 12 }}>
              <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                <strong style={{ overflowWrap: "anywhere" }}>{device.name ?? device.mac}</strong>
                <span className="small muted">{device.kind ? KIND_LABELS[device.kind] ?? device.kind : "Victron device"}</span>
                <span className="tiny faint">
                  {signal(device.rssi)} · {device.mac}
                </span>
              </span>
              {device.added_as ? (
                <span className="small c-ok" style={{ whiteSpace: "nowrap" }}>
                  ✓ {device.added_as}
                </span>
              ) : (
                <button type="button" className="btn small primary" onClick={() => onPick(device)}>
                  Add
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      <button type="button" className="btn ghost small" onClick={() => onPick("manual")} style={{ alignSelf: "flex-start" }}>
        Not in the list? Enter it by hand
      </button>
    </Card>
  );
}

function AddDialog({
  device,
  onClose,
  onAdded,
}: {
  device: VictronNearby | null;
  onClose: () => void;
  onAdded: (name: string, checked: boolean) => void;
}) {
  const add = useAddVictron();
  const [name, setName] = useState(device?.suggested_name ?? "");
  const [mac, setMac] = useState(device?.mac ?? "");
  const [key, setKey] = useState("");
  const cleanKey = key.replace(/\s/g, "").toLowerCase();
  const keyOk = KEY.test(cleanKey);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate(
      { name: name.trim().toLowerCase(), mac, key: cleanKey },
      { onSuccess: (result) => onAdded(result.name, result.key_checked) },
    );
  };

  return (
    <Dialog title={device ? `Add ${device.name ?? "device"}` : "Add a Victron device"} onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        {!device && (
          <Field label="MAC address" hint="In VictronConnect: ⚙ › Product info › Instant readout details.">
            <input className="input mono" value={mac} onChange={(e) => setMac(e.target.value)} placeholder="AA:BB:CC:DD:EE:FF" required autoCapitalize="characters" spellCheck={false} />
          </Field>
        )}
        <Field label="Encryption key" hint="32 characters. VictronConnect › ⚙ › Product info › Instant readout details › Show.">
          <input
            className="input mono"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="0123456789abcdef0123456789abcdef"
            required
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
          />
        </Field>
        {key && !keyOk && <span className="small c-danger">{cleanKey.length}/32 characters, only 0-9 and a-f.</span>}
        <Field label="Name" hint="Short and lowercase, used in rules and on the Energy page.">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} pattern="[a-zA-Z0-9_\-]{1,32}" required />
        </Field>
        <ErrorNote error={add.error} />
        <button type="submit" className="btn primary" disabled={!keyOk || add.isPending}>
          {add.isPending ? "Checking the key…" : "Add device"}
        </button>
        <span className="tiny faint">The key stays on the van and is never shown again.</span>
      </form>
    </Dialog>
  );
}
