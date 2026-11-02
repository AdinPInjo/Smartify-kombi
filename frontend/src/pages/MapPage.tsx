import { useState } from "react";
import { api } from "@/api/client";
import { useDistance, useGps, useGpsArchives, useTrack } from "@/api/hooks";
import { PageHeader } from "@/components/PageHeader";
import { TrackMap } from "@/components/TrackMap";
import { Card, Num, Segmented } from "@/components/ui";
import { ago, bytes, coords, fmt } from "@/lib/format";

const RANGES = [
  { value: "24", label: "24 h" },
  { value: "168", label: "7 days" },
  { value: "720", label: "30 days" },
  { value: "2160", label: "90 days" },
];

export function MapPage() {
  const [hours, setHours] = useState("24");
  const gps = useGps();
  const track = useTrack(Number(hours));
  const distance = useDistance();
  const archives = useGpsArchives();
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
            ? `${coords(fix.lat, fix.lon)} · ${fix.satellites ?? "–"} satellites`
            : gps.data?.status === "no_fix"
              ? "Searching for satellites…"
              : gps.data?.status === "no_device"
                ? `GPS not connected${gps.data.error ? `: ${gps.data.error}` : ""}`
                : "GPS disabled"
        }
      />
      <div style={{ maxWidth: 420 }}>
        <Segmented label="Time range" options={RANGES} value={hours} onChange={setHours} />
      </div>
      <section className="card flush" style={{ height: "min(62vh, 560px)" }}>
        <TrackMap
          key={hours}
          points={track.data ?? []}
          position={fix}
          height="100%"
          label={`Map with the route of the selected period, ${track.data?.length ?? 0} points`}
        />
      </section>
      <p className="tiny faint" style={{ margin: "-6px 4px 0" }}>
        Map tiles need internet. The route itself is recorded on the Pi either way.
      </p>

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
          {archives.data?.length === 0 && <span className="small faint">Nothing archived yet.</span>}
        </Card>
      </div>
    </main>
  );
}
