// Add a diesel heater over Bluetooth, like the Victron setup: pick it from the
// list of heaters nearby, give it a name and its PIN.

import { Bluetooth, CheckCircle2, Flame, Loader2, Radio } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMode } from "@/api/hooks";
import { useHeaters, type Heater } from "@/components/Heater";
import { PageHeader } from "@/components/PageHeader";
import { SetupGuide, type GuideStep } from "@/components/SetupGuide";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { Card, Dialog, ErrorNote, Field, useToast } from "@/components/ui";
import { change, type DashLayout } from "@/lib/dashLayout";
import { OVERVIEW, type OverviewCardId } from "@/lib/overviewLayout";
import { ago } from "@/lib/format";

interface Nearby {
  mac: string;
  name: string | null;
  rssi: number | null;
  seen_at: number;
  added: boolean;
}

/** Show the heater card on this device's overview (it starts hidden). */
function showOnOverview() {
  try {
    const raw = window.localStorage.getItem(OVERVIEW.key);
    const layout = (raw ? JSON.parse(raw) : { cards: OVERVIEW.cards.map(({ id, w, h, hidden }) => ({ id, w, h, hidden: hidden ?? false })) }) as DashLayout<OverviewCardId>;
    const has = layout.cards.some((c) => c.id === "heater");
    const next = has ? change(layout, "heater", { hidden: false }) : { cards: [{ id: "heater" as const, w: 3 as const, h: 1 as const, hidden: false }, ...layout.cards] };
    window.localStorage.setItem(OVERVIEW.key, JSON.stringify(next));
  } catch {
    /* storage unavailable: the card can still be shown with "Customize" */
  }
}

const HEATER_GUIDE: GuideStep[] = [
  {
    title: "What you need",
    body: (
      <>
        <p style={{ margin: 0 }}>
          If your diesel heater can be controlled with a phone app over Bluetooth, Smartify can control it too, and then you
          don't need the app any more. You need:
        </p>
        <ul className="guide-list">
          <li>
            A heater with Bluetooth. Its app is called something like <strong>AirHeaterBLE</strong>,{" "}
            <strong>Hcalory</strong>, <strong>Sunster</strong> or <strong>HeaterCC</strong> (Vevor, BYD and many other brands).
          </li>
          <li>The heater connected to 12 V (it doesn't need to be running).</li>
          <li>The Pi within a few metres of the heater's control panel.</li>
        </ul>
      </>
    ),
  },
  {
    title: "Find the PIN, then free the Bluetooth",
    body: (
      <>
        <p style={{ margin: 0 }}>
          The heater has a 4-digit <strong>PIN</strong>. Almost always it's <strong>1234</strong>. If you changed it in the
          heater's app, use yours.
        </p>
        <p style={{ margin: 0 }}>
          Then <strong>close the heater's app</strong> on your phone (swipe it away), or switch your phone's Bluetooth off for
          a moment. Most heaters accept only <strong>one</strong> connection at a time: while the app is connected,
          Smartify can't get in.
        </p>
      </>
    ),
  },
  {
    title: "Add it here",
    body: (
      <>
        <p style={{ margin: 0 }}>
          Under <strong>Heaters nearby</strong> on this page, your heater appears within about 20 seconds, often called{" "}
          <strong>“Air Heater”</strong>, “BYD-…”, “HC-…” or “Hcalory…”. Tap <strong>Add</strong>, give it a name and enter the
          PIN.
        </p>
        <p style={{ margin: 0 }}>Within a minute it shows <strong>Connected</strong>.</p>
      </>
    ),
    trouble: (
      <>
        <span>
          <strong>Not in the list?</strong> Check the heater has 12 V, move the Pi closer, and make sure no phone is
          connected to it (step 2).
        </span>
        <span>
          <strong>“Doesn't answer (wrong PIN?)”</strong> Remove it and add it again with the right PIN.
        </span>
        <span>
          <strong>“Doesn't look like a supported heater”</strong> Your model speaks a protocol Smartify doesn't know yet.
          Please open an issue on GitHub with the heater's name and that message, so it can be added.
        </span>
      </>
    ),
  },
  {
    title: "Try it",
    body: (
      <>
        <p style={{ margin: 0 }}>
          On the heater's card (Climate tab, or the overview after <strong>Show it on the overview</strong>), tap{" "}
          <strong>On</strong>. It runs a self-test, then ignites: that takes <strong>1 to 3 minutes</strong>, and you hear
          the fuel pump ticking. Then it shows <strong>Heating</strong>.
        </p>
        <p style={{ margin: 0 }}>
          Choose <strong>Temperature</strong> to keep the van at, say, 20 °C, or <strong>Power level</strong> for a fixed
          strength (1 to 10). Use <strong>− / +</strong> to change it.
        </p>
        <p style={{ margin: 0 }}>
          Tap <strong>Off</strong>: it shows <strong>Cooling down</strong> and the fan keeps blowing for a few minutes until
          the burner is cold. That's normal and protects the heater.
        </p>
      </>
    ),
  },
  {
    title: "Stay safe",
    body: (
      <ul className="guide-list">
        <li>
          <strong>Never switch the heater's 12 V with a relay</strong> or a switch while it runs. It must cool down first.
          Smartify always uses the heater's own Off.
        </li>
        <li>
          Fit a <strong>carbon monoxide (CO) detector</strong> in the van, and make sure the exhaust goes outside.
        </li>
        <li>Faults the heater reports (E-codes) are sent to your phone, if you've set up notifications.</li>
      </ul>
    ),
  },
];

export function HeaterSetup() {
  const { cloud } = useMode();
  const heaters = useHeaters();
  const [adding, setAdding] = useState<Nearby | null>(null);
  const [added, setAdded] = useState(false);
  const list = heaters.data?.heaters ?? [];

  return (
    <main className="page" style={{ maxWidth: 760 }}>
      <PageHeader
        kicker="Climate"
        title="Diesel heater"
        sub="Control your diesel heater from Smartify over Bluetooth, instead of its app."
        right={<Link to="/climate" className="small">Climate ›</Link>}
      />
      {cloud ? (
        <Card><OnlyOnVan what="Adding a heater" /></Card>
      ) : (
        <>
          <SetupGuide id="heater" title="Connect your diesel heater" steps={HEATER_GUIDE} startOpen={list.length === 0} />
          <Card label="Your heaters">
            {list.length === 0 && <span className="small muted">None yet. Pick yours from the list below.</span>}
            <div className="list">
              {list.map((heater) => <Configured key={heater.id} heater={heater} />)}
            </div>
            {added && (
              <div className="notice ok stack" style={{ gap: 8 }}>
                <span className="row" style={{ gap: 8 }}><CheckCircle2 size={18} aria-hidden="true" /> Added. It connects within a minute.</span>
                <button type="button" className="btn small" style={{ alignSelf: "flex-start" }} onClick={() => { showOnOverview(); setAdded(false); }}>
                  Show it on the overview
                </button>
              </div>
            )}
          </Card>
          <NearbyList onPick={setAdding} />
          {adding && <AddDialog nearby={adding} onClose={() => setAdding(null)} onAdded={() => { setAdding(null); setAdded(true); }} />}
        </>
      )}
    </main>
  );
}

function Configured({ heater }: { heater: Heater }) {
  const client = useQueryClient();
  const toast = useToast();
  const remove = useMutation({
    mutationFn: () => api.delete(`/heaters/${heater.id}`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["heaters"] });
      toast("Heater removed");
    },
  });
  return (
    <div className="row-between" style={{ gap: 10 }}>
      <span className="stack" style={{ gap: 2, minWidth: 0 }}>
        <strong className="row" style={{ gap: 8 }}><Flame size={16} aria-hidden="true" /> {heater.name}</strong>
        <span className="tiny muted mono">{heater.mac}</span>
        <span className="tiny muted">
          {heater.connected
            ? `Connected · ${heater.status?.protocol ?? "reading"} · ${heater.status?.phase_name ?? ""}`
            : (heater.error ?? "connecting…")}
        </span>
      </span>
      <button type="button" className="btn small ghost" disabled={remove.isPending}
        onClick={() => window.confirm(`Remove ${heater.name}? Smartify stops controlling it; the heater itself keeps its settings.`) && remove.mutate()}>
        Remove
      </button>
    </div>
  );
}

function NearbyList({ onPick }: { onPick: (heater: Nearby) => void }) {
  const nearby = useQuery({
    queryKey: ["heaters", "nearby"],
    queryFn: () => api.get<{ heaters: Nearby[] }>("/heaters/nearby").then((r) => r.heaters),
    refetchInterval: 4_000,
  });
  const list = nearby.data ?? [];
  return (
    <Card label={<span className="row" style={{ gap: 8 }}><Radio size={16} aria-hidden="true" /> Heaters nearby</span>}>
      {list.length === 0 ? (
        <span className="row small muted" style={{ gap: 8 }}>
          <Loader2 size={16} className="spin" aria-hidden="true" /> Looking for heaters… Switch the heater's power on and keep it within
          a few metres of the Pi.
        </span>
      ) : (
        <div className="list">
          {list.map((heater) => (
            <div key={heater.mac} className="row-between" style={{ gap: 10 }}>
              <span className="stack" style={{ gap: 2 }}>
                <strong className="row" style={{ gap: 8 }}><Bluetooth size={16} aria-hidden="true" /> {heater.name ?? "Heater"}</strong>
                <span className="tiny muted mono">
                  {heater.mac} · {heater.rssi ?? "–"} dBm · {ago(heater.seen_at)}
                </span>
              </span>
              {heater.added ? (
                <span className="chip">added</span>
              ) : (
                <button type="button" className="btn small primary" onClick={() => onPick(heater)}>Add</button>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function AddDialog({ nearby, onClose, onAdded }: { nearby: Nearby; onClose: () => void; onAdded: () => void }) {
  const client = useQueryClient();
  const [name, setName] = useState("Diesel heater");
  const [pin, setPin] = useState("1234");
  const add = useMutation({
    mutationFn: () => api.post<Heater>("/heaters", { name, mac: nearby.mac, pin: Number(pin) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["heaters"] });
      onAdded();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };
  return (
    <Dialog title="Add heater" onClose={onClose}>
      <form className="stack" style={{ gap: 14 }} onSubmit={submit}>
        <span className="small muted">{nearby.name ?? "Heater"} · <span className="mono">{nearby.mac}</span></span>
        <Field label="Name">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={30} required />
        </Field>
        <Field label="PIN" hint="From the heater's app. Most heaters: 1234.">
          <input className="input mono" inputMode="numeric" pattern="[0-9]{4}" value={pin} onChange={(e) => setPin(e.target.value)} required />
        </Field>
        <ErrorNote error={add.error} />
        <button type="submit" className="btn primary" disabled={add.isPending}>{add.isPending ? "Adding…" : "Add heater"}</button>
      </form>
    </Dialog>
  );
}
