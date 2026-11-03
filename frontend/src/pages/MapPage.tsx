import { useState } from "react";
import { api } from "@/api/client";
import { useDistance, useGps, useGpsArchives, useMode, useStops, useTrack } from "@/api/hooks";
import type { Stop } from "@/api/types";
import { OnlyOnVan } from "@/components/RemoteBanner";
import { PageHeader } from "@/components/PageHeader";
import { TrackMap } from "@/components/TrackMap";
import { TrackScrubber, pointAt } from "@/components/TrackScrubber";
import { Card, Num, Segmented } from "@/components/ui";
import { ago, bytes, coords, duration, fmt } from "@/lib/format";

const RANGES = [
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
  { value: "720", label: "30 days" },
  { value: "2160", label: "90 days" },
];

export function MapPage() {
  const [hours, setHours] = useState("24");
  // Time picked with the slider under the map; null = now (whole route, live position).
  const [time, setTime] = useState<number | null>(null);
  const gps = useGps();
  const track = useTrack(Number(hours));
  const distance = useDistance();
  const archives = useGpsArchives();
  const { cloud } = useMode();
  const fix = gps.data?.fix ?? null;
  const days = distance.data?.days ?? [];
  const maxKm = Math.max(1, ...days.map((d) => d.distance_km));

  return (
    <main className="page">
      <PageHeader
        kicker="Map"
        title="Where we've been"
        sub={
          gps.data?.status === "ok" && fix
            ? `${coords(fix.lat, fix.lon)} · ${fix.satellites ?? "–"} satellites${gps.data.parked ? " · parked" : ""}`
            : gps.data?.status === "no_fix"
              ? "Searching for satellites…"
              : gps.data?.status === "no_device"
                ? `GPS not connected${gps.data.error ? `: ${gps.data.error}` : ""}`
                : "GPS disabled"
        }
      />
      <div style={{ maxWidth: 420 }}>
        <Segmented label="Time range" options={RANGES} value={hours} onChange={(value) => {
            setHours(value);
            setTime(null);
          }}
        />
      </div>
      <section className="card flush" style={{ height: "min(62vh, 560px)" }}>
        <TrackMap
          key={hours}
          points={track.data ?? []}
          position={fix}
          cursor={time === null ? null : pointAt(track.data ?? [], time)}
          height="100%"
          label={`Map with the route of the selected period, ${track.data?.length ?? 0} points`}
        />
      </section>
      <section className="card flush">
        <TrackScrubber points={track.data ?? []} time={time} onChange={setTime} />
      </section>
      <p className="tiny faint" style={{ margin: "-6px 4px 0" }}>
        Map tiles need internet. The route itself is recorded on the Pi either way.
      </p>

      <TravelLog />

      <div className="grid">
        <Card label="Distance">
          <div className="row" style={{ gap: 24 }}>
            <div className="stack" style={{ gap: 2 }}>
              <span className="tiny muted">Total</span>
              <Num value={fmt(distance.data?.total_km ?? null, 0)} unit="km" size="l" />
            </div>
            <div className="stack" style={{ gap: 2 }}>
              <span className="tiny muted">Speed now</span>
              <Num value={fmt(fix?.speed_kmh ?? null, 0)} unit="km/h" size="l" />
            </div>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            {days.slice(0, 14).map((day) => (
              <div key={day.day} className="row small">
                <span className="mono tiny muted" style={{ width: 86 }}>{day.day}</span>
                <div style={{ flex: 1, height: 10, background: "var(--surface-2)", borderRadius: 4 }}>
                  <div style={{ width: `${(day.distance_km / maxKm) * 100}%`, height: "100%", background: "var(--accent)", borderRadius: 4 }} />
                </div>
                <span style={{ width: 64, textAlign: "right" }}>{fmt(day.distance_km, 1)} km</span>
              </div>
            ))}
            {days.length === 0 && <span className="muted small">No driving recorded yet.</span>}
          </div>
        </Card>

        <Card label="Archive (GPX)">
          <p className="small muted" style={{ margin: 0 }}>
            Routes older than 90 days move from the database into monthly GPX files. They open in Komoot, Strava, Google Earth
            and video tools.
          </p>
          <div className="list">
            {archives.data?.map((file) => (
              <div key={file.name} className="row-between">
                <span>
                  <strong>{file.name.replace(".gpx", "")}</strong>{" "}
                  <span className="small muted">
                    {bytes(file.bytes)} · updated {ago(file.updated_at)}
                  </span>
                </span>
                <a className="btn small" href={api.url(`/gps/archive/${file.name}`)} download>
                  Download
                </a>
              </div>
            ))}
          </div>
          {cloud && <OnlyOnVan what="Downloading the GPX archive" />}
          {!cloud && archives.data?.length === 0 && <span className="small faint">Nothing archived yet.</span>}
        </Card>
      </div>
    </main>
  );
}

function stayText(stop: Stop): string {
  if (stop.nights > 0) return `${stop.nights} ${stop.nights === 1 ? "night" : "nights"}`;
  return duration(stop.duration_seconds);
}

function dates(stop: Stop): string {
  const day = (ts: number) => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short" });
  const start = day(stop.arrived_at);
  if (stop.here_now) return `since ${start}`;
  const end = day(stop.left_at!);
  return start === end ? start : `${start} – ${end}`;
}

/** Automatic travel log: every place the van stood for an hour or more. */
function TravelLog() {
  const stops = useStops();
  const [all, setAll] = useState(false);
  const list = stops.data ?? [];
  const shown = all ? list : list.slice(0, 8);
  const nights = list.reduce((sum, stop) => sum + stop.nights, 0);
  const countries = new Set(list.map((s) => s.country).filter(Boolean));

  return (
    <Card
      label="Travel log"
      action={
        list.length > 0 && (
          <span className="small muted">
            {list.length} stops · {nights} nights{countries.size > 1 ? ` · ${countries.size} countries` : ""}
          </span>
        )
      }
    >
      {list.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>
          Every place the van stands for an hour or more is added here automatically, with the place name, how long you
          stayed and the km driven to get there.
        </p>
      ) : (
        <div className="list">
          {shown.map((stop) => (
            <div key={stop.id} className="row-between" style={{ gap: 12, alignItems: "flex-start" }}>
              <span className="stack" style={{ gap: 2, minWidth: 0 }}>
                <a
                  href={`https://www.openstreetmap.org/?mlat=${stop.lat}&mlon=${stop.lon}#map=14/${stop.lat}/${stop.lon}`}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "inherit" }}
                >
                  <strong>{stop.place ?? coords(stop.lat, stop.lon)}</strong>
                  {stop.country && <span className="small muted"> · {stop.country}</span>}
                </a>
                <span className="small muted">
                  {dates(stop)} · {stayText(stop)}
                  {stop.here_now && <span className="c-accent"> · here now</span>}
                </span>
              </span>
              <span className="small muted" style={{ whiteSpace: "nowrap" }}>
                {stop.km_from_previous !== null ? `+${fmt(stop.km_from_previous, 0)} km` : ""}
              </span>
            </div>
          ))}
        </div>
      )}
      {list.length > 8 && (
        <button type="button" className="btn ghost small" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${list.length}`}
        </button>
      )}
    </Card>
  );
}
