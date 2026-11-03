import { ArrowLeft, ArrowRight, Car, EyeOff, GripVertical, LayoutGrid, Plus, SunMedium, Zap } from "lucide-react";
import { useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  useClimate,
  useClimateHistory,
  useDistance,
  useEnergy,
  useGps,
  useRelays,
  useTrack,
  useWater,
  useWeather,
} from "@/api/hooks";
import { batteryColor, LineChart, RingGauge, Tank } from "@/components/instruments";
import { PageHeader } from "@/components/PageHeader";
import { RelayControl } from "@/components/RelayControl";
import { TrackMap } from "@/components/TrackMap";
import { Card, Num, Skeleton } from "@/components/ui";
import { coords, duration, fmt, humanize, localDay, signed, weatherText } from "@/lib/format";
import {
  change,
  moveTo,
  OVERVIEW_CARDS,
  step,
  useOverviewLayout,
  WIDTHS,
  type CardLayout,
  type OverviewCardId,
  type OverviewLayout,
} from "@/lib/overviewLayout";
import { useNow } from "@/lib/useNow";

const LABEL = Object.fromEntries(OVERVIEW_CARDS.map((c) => [c.id, c.label])) as Record<OverviewCardId, string>;

export function Overview() {
  const { layout, save, reset } = useOverviewLayout();
  const [params, setParams] = useSearchParams();
  const editing = params.get("edit") === "1";
  const setEditing = (on: boolean) => setParams(on ? { edit: "1" } : {}, { replace: true });
  const gps = useGps();
  const now = useNow();
  const fix = gps.data?.fix;
  const drag = useDrag(layout, save);
  const visible = layout.cards.filter((c) => !c.hidden);
  const hidden = layout.cards.filter((c) => c.hidden);

  return (
    <main className="page">
      <PageHeader
        kicker="Smartify · Kombi"
        title={editing ? "Customize" : "Kombi"}
        sub={
          editing
            ? "Drag cards by their handle, pick a width and height."
            : fix
              ? `${fix.altitude_m !== null ? `${Math.round(fix.altitude_m)} m · ` : ""}${fix.satellites ?? "–"} sats · ${
                  (fix.speed_kmh ?? 0) >= 3 ? `${Math.round(fix.speed_kmh ?? 0)} km/h` : "parked"
                }`
              : gps.data?.status === "disabled"
                ? "GPS off"
                : "Waiting for GPS"
        }
        right={
          editing ? (
            <div className="row" style={{ gap: 6 }}>
              <button type="button" className="btn small ghost" onClick={() => window.confirm("Back to the standard layout?") && reset()}>
                Reset
              </button>
              <button type="button" className="btn small primary" onClick={() => setEditing(false)}>
                Done
              </button>
            </div>
          ) : (
            <div className="row" style={{ gap: 6 }}>
              <span className="chip">
                <span className="dot ok" />
                {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>
              <button type="button" className="btn small ghost icon-only" aria-label="Customize the overview" onClick={() => setEditing(true)}>
                <LayoutGrid size={18} aria-hidden="true" />
              </button>
            </div>
          )
        }
      />
      <div className={`dash ${editing ? "editing" : ""}`}>
        {visible.map((card, index) => (
          <div
            key={card.id}
            data-card={card.id}
            className={`dash-item ${drag.dragging === card.id ? "dragging" : ""}`}
            style={{ "--w": card.w, "--wm": card.w >= 4 ? 2 : 1, "--h": card.h } as CSSProperties}
          >
            <OverviewCard id={card.id} tall={card.h === 2} />
            {editing && (
              <EditBar
                card={card}
                first={index === 0}
                last={index === visible.length - 1}
                onChange={(values) => save(change(layout, card.id, values))}
                onStep={(direction) => save(step(layout, card.id, direction))}
                handle={drag.handle(card.id)}
              />
            )}
          </div>
        ))}
      </div>
      {editing && hidden.length > 0 && (
        <div className="row wrap" style={{ gap: 8 }}>
          <span className="small muted">Hidden:</span>
          {hidden.map((card) => (
            <button key={card.id} type="button" className="btn small" onClick={() => save(change(layout, card.id, { hidden: false }))}>
              <Plus size={16} aria-hidden="true" /> {LABEL[card.id]}
            </button>
          ))}
        </div>
      )}
      {!editing && (
        <button type="button" className="btn small ghost" style={{ alignSelf: "center" }} onClick={() => setEditing(true)}>
          Customize overview
        </button>
      )}
    </main>
  );
}

/** Drag a card by its handle (mouse, finger or pen); the others make room live. */
function useDrag(layout: OverviewLayout, save: (layout: OverviewLayout) => void) {
  const [dragging, setDragging] = useState<OverviewCardId | null>(null);
  const latest = useRef(layout);
  latest.current = layout;
  const lastTarget = useRef<string | null>(null);

  const handle = (id: OverviewCardId) => ({
    onPointerDown: (event: ReactPointerEvent<HTMLElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      lastTarget.current = null;
      setDragging(id);
    },
    onPointerMove: (event: ReactPointerEvent<HTMLElement>) => {
      if (dragging !== id) return;
      // Scroll when dragging near the top or bottom edge of the screen.
      if (event.clientY < 70) window.scrollBy(0, -14);
      else if (event.clientY > window.innerHeight - 110) window.scrollBy(0, 14);
      const over = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>("[data-card]");
      const target = over?.dataset.card as OverviewCardId | undefined;
      if (!target || target === id) {
        lastTarget.current = null;
        return;
      }
      // After a swap the other card may now sit under the finger: don't swap back.
      if (target === lastTarget.current) return;
      lastTarget.current = target;
      save(moveTo(latest.current, id, target));
    },
    onPointerUp: () => setDragging(null),
    onPointerCancel: () => setDragging(null),
  });
  return { dragging, handle };
}

function EditBar({
  card,
  first,
  last,
  onChange,
  onStep,
  handle,
}: {
  card: CardLayout;
  first: boolean;
  last: boolean;
  onChange: (values: Partial<Omit<CardLayout, "id">>) => void;
  onStep: (direction: -1 | 1) => void;
  handle: ReturnType<ReturnType<typeof useDrag>["handle"]>;
}) {
  const label = LABEL[card.id];
  return (
    <div className="dash-edit" role="group" aria-label={`${label}: layout`}>
      <div className="dash-edit-top">
        <button type="button" className="dash-handle" aria-label={`Drag ${label}`} {...handle}>
          <GripVertical size={20} aria-hidden="true" />
        </button>
        <strong className="small grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
        </strong>
        <button type="button" className="dash-icon" aria-label={`Move ${label} earlier`} disabled={first} onClick={() => onStep(-1)}>
          <ArrowLeft size={18} aria-hidden="true" />
        </button>
        <button type="button" className="dash-icon" aria-label={`Move ${label} later`} disabled={last} onClick={() => onStep(1)}>
          <ArrowRight size={18} aria-hidden="true" />
        </button>
        <button type="button" className="dash-icon" aria-label={`Hide ${label}`} onClick={() => onChange({ hidden: true })}>
          <EyeOff size={18} aria-hidden="true" />
        </button>
      </div>
      <div className="dash-options" role="group" aria-label="Width">
        {WIDTHS.map((width) => (
          <button
            key={width.value}
            type="button"
            className={card.w === width.value ? "on" : ""}
            aria-pressed={card.w === width.value}
            aria-label={`Width: ${width.name}`}
            onClick={() => onChange({ w: width.value })}
          >
            {width.label}
          </button>
        ))}
      </div>
      <div className="dash-options" role="group" aria-label="Height">
        {([1, 2] as const).map((h) => (
          <button
            key={h}
            type="button"
            className={card.h === h ? "on" : ""}
            aria-pressed={card.h === h}
            onClick={() => onChange({ h })}
          >
            {h === 1 ? "1 row" : "2 rows"}
          </button>
        ))}
      </div>
    </div>
  );
}

function OverviewCard({ id, tall }: { id: OverviewCardId; tall: boolean }) {
  switch (id) {
    case "climate":
      return <ClimateCard tall={tall} />;
    case "battery":
      return <BatteryCard />;
    case "water":
      return <WaterCard />;
    case "charging":
      return <ChargingCard />;
    case "switches":
      return <SwitchesCard />;
    case "map":
      return <MapCard tall={tall} />;
  }
}

function ClimateCard({ tall }: { tall: boolean }) {
  const climate = useClimate();
  const weather = useWeather();
  const [inside, outside] = climate.data ?? [];
  const history = useClimateHistory(inside?.sensor, 6);
  const points = history.data ?? [];
  const tomorrow = weather.data?.forecast?.[1];
  if (climate.isPending) return <Card label="Cabin"><Skeleton height={160} /></Card>;
  if (!inside) return <Card label="Cabin"><p className="muted">No temperature sensors configured.</p></Card>;
  return (
    <Card label={`Cabin · ${inside.sensor}`} action={<Link to="/climate" className="small">Climate ›</Link>}>
      <div className="row-between" style={{ alignItems: "flex-end" }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 2 }}>
          <span className="num num-xxl">{fmt(inside.temperature_c)}</span>
          <span className="num c-accent" style={{ fontSize: 34, fontWeight: 500 }}>°C</span>
        </div>
        <div className="stack" style={{ alignItems: "flex-end", gap: 8, paddingBottom: 4 }}>
          {outside && (
            <div className="row" style={{ alignItems: "baseline" }}>
              <span className="tiny muted">{outside.sensor}</span>
              <Num value={`${fmt(outside.temperature_c)}°`} size="m" />
            </div>
          )}
          <div className="row" style={{ alignItems: "baseline" }}>
            <span className="tiny muted">Humidity</span>
            <Num value={`${fmt(inside.humidity, 0)}%`} size="m" />
          </div>
        </div>
      </div>
      {inside.status !== "ready" && (
        <div className="small c-accent">
          {inside.status === "warming_up" ? "Sensor warming up…" : `Sensor not responding${inside.last_error ? `: ${inside.last_error}` : ""}`}
        </div>
      )}
      <LineChart
        label="Inside temperature, last 6 hours"
        unit="°C"
        height={tall ? 200 : 48}
        times={points.map((p) => p.created_at)}
        series={[{ label: "Inside", values: points.map((p) => p.temperature_c), color: "var(--accent)", fill: true }]}
      />
      <div className="row-between small muted divider">
        <span>
          {weather.data?.available
            ? `Weather · ${fmt(weather.data.temperature_c, 0)}° ${weatherText(weather.data.weather_code)}`
            : "Weather unavailable"}
        </span>
        {tomorrow && (
          <span>
            Tomorrow {Math.round(tomorrow.temperature_max)}° / {signed(Math.round(tomorrow.temperature_min), 0).replace("+", "")}°
          </span>
        )}
      </div>
    </Card>
  );
}

function BatteryCard() {
  const energy = useEnergy();
  const water = useWater();
  const battery = energy.data?.battery;
  const soc = battery?.soc ?? null;
  const voltage = battery?.voltage ?? water.data?.battery_voltage ?? null;
  return (
    <Card label="Battery" action={<Link to="/energy" className="small" aria-label="Energy details">›</Link>}>
      <div style={{ alignSelf: "center" }}>
        <RingGauge value={soc} color={batteryColor(soc)} label={soc === null ? "Battery charge unknown" : `Battery ${soc} percent`}>
          {soc !== null ? (
            <>
              <Num value={Math.round(soc)} unit="%" size="l" />
              <span className="tiny muted">
                {battery?.remaining_mins ? `~${duration(battery.remaining_mins * 60)}` : battery?.current && battery.current > 0 ? "charging" : ""}
              </span>
            </>
          ) : (
            <span className="small muted">no shunt</span>
          )}
        </RingGauge>
      </div>
      <div className="row-between">
        <Num value={fmt(voltage, 2)} unit="V" size="s" />
        <Num
          value={signed(battery?.current ?? null)}
          unit="A"
          size="s"
          className={(battery?.current ?? 0) < 0 ? "c-alert" : "c-ok"}
        />
      </div>
    </Card>
  );
}

function WaterCard() {
  const water = useWater();
  const level = water.data?.level_percent ?? null;
  return (
    <Card label="Fresh water" action={<Link to="/climate#water" className="small" aria-label="Water details">›</Link>}>
      <div className="row" style={{ alignItems: "flex-end", height: 120, gap: 14 }}>
        <Tank percent={level} />
        <div className="stack" style={{ gap: 2 }}>
          <Num value={level ?? "–"} unit="%" size="l" />
        </div>
      </div>
      <div className={`small ${water.data?.ok === false ? "c-accent" : "muted"}`}>
        {water.data?.ok ? "Sensor ok" : (water.data?.error ?? "No reading yet")}
      </div>
    </Card>
  );
}

function ChargingCard() {
  const energy = useEnergy();
  const e = energy.data;
  if (!e?.available) {
    return (
      <Card label="Charging">
        <p className="muted small" style={{ margin: 0 }}>
          No Victron data yet. <Link to="/energy/devices">Add your Victron devices ›</Link>
        </p>
      </Card>
    );
  }
  const driving = e.dcdc?.charge_state && e.dcdc.charge_state !== "off";
  return (
    <Card label="Charging" action={<Link to="/energy" className="small">Energy ›</Link>}>
      <div className="grid-3">
        <div className={`tile ${(e.solar?.power ?? 0) > 0 ? "highlight" : ""}`}>
          <SunMedium size={20} color="var(--solar)" aria-hidden="true" />
          <Num value={fmt(e.solar?.power ?? null, 0)} unit="W" size="m" />
          <span className="tiny muted">Solar · {fmt((e.solar?.yield_today_wh ?? 0) / 1000, 1)} kWh</span>
        </div>
        <div className={`tile ${driving ? "highlight" : ""}`}>
          <Car size={20} color="var(--accent)" aria-hidden="true" />
          <Num value={fmt(e.dcdc?.output_current ?? null, 1)} unit="A" size="m" />
          <span className="tiny muted">Orion · {humanize(e.dcdc?.charge_state)}</span>
        </div>
        <div className="tile">
          <Zap size={20} aria-hidden="true" />
          <Num value={fmt(e.inverter?.ac_out_power ?? null, 0)} unit="W" size="m" />
          <span className="tiny muted">{humanize(e.inverter?.state)}</span>
        </div>
      </div>
    </Card>
  );
}

function SwitchesCard() {
  const relays = useRelays();
  return (
    <Card label="Switches" action={<Link to="/switches" className="small">Rules ›</Link>}>
      {relays.isPending && <Skeleton height={120} />}
      {relays.data?.length === 0 && <p className="muted">No relays yet.</p>}
      <div className="grid">
        {relays.data?.map((relay) => <RelayControl key={relay.id} relay={relay} />)}
      </div>
    </Card>
  );
}

function MapCard({ tall }: { tall: boolean }) {
  const gps = useGps();
  const track = useTrack(24);
  const fix = gps.data?.fix ?? null;
  return (
    <section className="card flush">
      <TrackMap
        points={track.data ?? []}
        position={fix}
        height={tall ? 470 : 190}
        interactive={false}
        label="Map of the last 24 hours with the current position"
      />
      <div className="row-between" style={{ padding: "12px 16px" }}>
        <div className="stack" style={{ gap: 2 }}>
          <span className="mono small">{fix ? coords(fix.lat, fix.lon) : "No position yet"}</span>
          <TodayDistance />
        </div>
        <Link to="/map" className="small">Map ›</Link>
      </div>
    </section>
  );
}

function TodayDistance() {
  const today = localDay(new Date());
  const distance = useDistance().data;
  const km = distance?.days.find((d) => d.day === today)?.distance_km ?? 0;
  return (
    <span className="small muted">
      Today {fmt(km, 1)} km · total {fmt(distance?.total_km ?? null, 0)} km
    </span>
  );
}
