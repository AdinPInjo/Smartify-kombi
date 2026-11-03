import { useState, type FormEvent } from "react";
import { useCreateRelay, useMode, useRelays } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { RelayControl } from "@/components/RelayControl";
import { ScenesCard } from "@/components/Scenes";
import { Dialog, ErrorNote, Field, Skeleton, useToast } from "@/components/ui";

export function Switches() {
  const relays = useRelays();
  const [adding, setAdding] = useState(false);
  const { cloud } = useMode();
  return (
    <main className="page">
      <PageHeader
        kicker="Switches"
        title="Relays & rules"
        sub="Use “Rules” on a switch to make it work automatically. Tap its name for all settings."
        right={
          cloud ? undefined : (
            <button type="button" className="btn small" onClick={() => setAdding(true)}>
              Add relay
            </button>
          )
        }
      />
      {relays.isPending && <Skeleton height={160} />}
      <div className="grid">
        {relays.data?.map((relay) => <RelayControl key={relay.id} relay={relay} large />)}
      </div>
      <ScenesCard />
      {adding && <AddRelayDialog onClose={() => setAdding(false)} />}
    </main>
  );
}

function AddRelayDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateRelay();
  const toast = useToast();
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [pin, setPin] = useState("");
  const [activeLow, setActiveLow] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { name: name.trim().toLowerCase(), label: label.trim() || undefined, gpio_pin: Number(pin), active_low: activeLow },
      {
        onSuccess: (relay) => {
          toast(`${relay.label || relay.name} added`);
          onClose();
        },
      },
    );
  };

  return (
    <Dialog title="Add relay" onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <Field label="Name (used in rules: lowercase, no spaces)">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} pattern="[a-z0-9_\-]{1,32}" required />
        </Field>
        <Field label="Label shown in the dashboard (optional)">
          <input className="input" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} />
        </Field>
        <Field label="GPIO pin (BCM number)" hint="Not 0–3 or 14–15 (HAT EEPROM, I2C, GPS serial) and not a DHT22 pin.">
          <input className="input" type="number" min={0} max={27} value={pin} onChange={(e) => setPin(e.target.value)} required />
        </Field>
        <label className="switch-row">
          <span>Relay board switches on a LOW signal (active-low)</span>
          <input type="checkbox" checked={activeLow} onChange={(e) => setActiveLow(e.target.checked)} />
        </label>
        <ErrorNote error={create.error} />
        <button type="submit" className="btn primary" disabled={create.isPending}>
          Add relay
        </button>
      </form>
    </Dialog>
  );
}
