import { useEffect, useMemo, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { MapPin, Navigation, Car, Warehouse, Thermometer, Battery, Power } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/utils";

type TempPayload = {
  ts: number | null;
  kombi: { temp_c: number | null; hum_pct: number | null };
  garaza: { temp_c: number | null; hum_pct: number | null };
};

type GpsPayload = {
  ts: string | number | null;
  lat: number | null;
  lon: number | null;
  speed_m_s: number | null;
  mode: number | null;
  connected?: boolean;
  age_s?: number;
};

type TrackPoint = { ts: string; lat: number; lon: number; speed_m_s?: number | null; mode?: number | null };
type TrackPayload = { hours: number; count: number; points: TrackPoint[] };

function formatTemp(t: number | null) {
  return t == null ? "—" : `${t.toFixed(1)}°C`;
}
function formatHum(h: number | null) {
  return h == null ? "" : `${h.toFixed(0)}%`;
}
function tempClass(t: number | null) {
  if (t == null) return "border-zinc-700 bg-zinc-900/40";
  if (t < 8) return "border-sky-500/40 bg-sky-500/10";
  if (t < 16) return "border-emerald-500/40 bg-emerald-500/10";
  if (t < 24) return "border-amber-500/40 bg-amber-500/10";
  return "border-red-500/40 bg-red-500/10";
}

function GpsMiniMap({ lat, lon }: { lat: number | null; lon: number | null }) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    if (mapRef.current) return;

    const map = L.map(elRef.current, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false as any,
      touchZoom: false,
    }).setView([43.8563, 18.4131], 10);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (lat == null || lon == null) return;

    map.setView([lat, lon], 14);

    if (!markerRef.current) {
      markerRef.current = L.circleMarker([lat, lon], { radius: 6 });
      markerRef.current.addTo(map);
    } else {
      markerRef.current.setLatLng([lat, lon]);
    }
  }, [lat, lon]);

  return <div ref={elRef} className="h-28 w-full rounded-xl overflow-hidden" />;
}

function GpsTrackMap({ data }: { data: TrackPayload | null }) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    if (mapRef.current) return;

    const map = L.map(elRef.current, { zoomControl: true, attributionControl: true }).setView([43.8563, 18.4131], 9);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();

    const pts = data?.points ?? [];
    if (pts.length === 0) return;

    const latlngs: L.LatLngExpression[] = pts.map((p) => [p.lat, p.lon]);
    const poly = L.polyline(latlngs, { weight: 4 });
    poly.addTo(layer);

    const last = pts[pts.length - 1];
    L.circleMarker([last.lat, last.lon], { radius: 7 }).addTo(layer);

    map.fitBounds(poly.getBounds(), { padding: [20, 20] });
  }, [data]);

  return <div ref={elRef} className="h-[420px] w-full rounded-2xl overflow-hidden" />;
}

export default function OverviewDashboard() {
  const [temps, setTemps] = useState<TempPayload | null>(null);
  const [gps, setGps] = useState<GpsPayload | null>(null);
  const [track, setTrack] = useState<TrackPayload | null>(null);

  // Temps
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch("/api/temperature/latest", { cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as TempPayload;
        if (alive) setTemps(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // GPS current
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch("/api/gps/current", { cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as GpsPayload;
        if (alive) setGps(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // GPS track (24h)
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch("/api/gps/track?hours=24", { cache: "no-store" });
        if (!r.ok) return;
        const j = (await r.json()) as TrackPayload;
        if (alive) setTrack(j);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const gpsHasFix = gps?.lat != null && gps?.lon != null;
  const speedKmh = useMemo(() => (gps?.speed_m_s == null ? null : gps.speed_m_s * 3.6), [gps?.speed_m_s]);

  const kombiT = temps?.kombi?.temp_c ?? null;

  const gpsStatus =
    gps?.connected === false ? "Disconnected" : gpsHasFix ? "Fix" : "No fix";

  return (
    <div className="space-y-4">
      {/* TOP: 4 cards */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {/* 1) GPS mini */}
        <Card className="rounded-2xl border shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <MapPin className="h-5 w-5" />
              Van location
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <GpsMiniMap lat={gps?.lat ?? null} lon={gps?.lon ?? null} />

            <div className="flex items-center justify-between text-sm">
              <span className="opacity-80">Status</span>
              <span className="font-medium">{gpsStatus}</span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className="opacity-80">Lat / Lon</span>
              <span className="font-medium tabular-nums">
                {gpsHasFix ? `${gps?.lat?.toFixed(5)}, ${gps?.lon?.toFixed(5)}` : "—"}
              </span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className="opacity-80 flex items-center gap-2">
                <Navigation className="h-4 w-4" />
                Speed
              </span>
              <span className="font-medium tabular-nums">
                {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* 2) Temperatures */}
        <Card className={`rounded-2xl border shadow-sm ${tempClass(kombiT)}`}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Thermometer className="h-5 w-5" />
              Temperatures
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between rounded-xl bg-black/20 px-3 py-2 text-sm">
              <span className="flex items-center gap-2 opacity-90">
                <Car className="h-4 w-4" />
                Kombi
              </span>
              <span className="font-medium tabular-nums">
                {formatTemp(temps?.kombi?.temp_c ?? null)}
                <span className="ml-2 text-xs opacity-70">{formatHum(temps?.kombi?.hum_pct ?? null)}</span>
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl bg-black/20 px-3 py-2 text-sm">
              <span className="flex items-center gap-2 opacity-90">
                <Warehouse className="h-4 w-4" />
                Garaža
              </span>
              <span className="font-medium tabular-nums">
                {formatTemp(temps?.garaza?.temp_c ?? null)}
                <span className="ml-2 text-xs opacity-70">{formatHum(temps?.garaza?.hum_pct ?? null)}</span>
              </span>
            </div>
          </CardContent>
        </Card>

        {/* 3) Battery (placeholder) */}
        <Card className="rounded-2xl border shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Battery className="h-5 w-5" />
              Battery
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="opacity-80">State of charge</span>
              <span className="font-medium">— %</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="opacity-80">Voltage</span>
              <span className="font-medium">— V</span>
            </div>
          </CardContent>
        </Card>

        {/* 4) Heater (placeholder) */}
        <Card className="rounded-2xl border shadow-sm">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Power className="h-5 w-5" />
              Heater
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="opacity-80">Status</span>
              <span className="font-medium">—</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="opacity-80">Mode</span>
              <span className="font-medium">—</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* BELOW: Big map + 24h track */}
      <Card className="rounded-2xl border shadow-sm">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">GPS map &amp; last 24h history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <GpsTrackMap data={track} />

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-xl bg-black/20 px-3 py-2 text-sm flex items-center justify-between">
              <span className="opacity-80">Points</span>
              <span className="font-medium tabular-nums">{track?.count ?? 0}</span>
            </div>
            <div className="rounded-xl bg-black/20 px-3 py-2 text-sm flex items-center justify-between">
              <span className="opacity-80">Speed</span>
              <span className="font-medium tabular-nums">
                {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
              </span>
            </div>
            <div className="rounded-xl bg-black/20 px-3 py-2 text-sm flex items-center justify-between">
              <span className="opacity-80">Status</span>
              <span className="font-medium">{gpsStatus}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
