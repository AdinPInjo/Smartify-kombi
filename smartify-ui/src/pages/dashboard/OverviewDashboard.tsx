import { useEffect, useMemo, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { MapPin, Navigation, Car, Warehouse, Thermometer, Battery, Power, Droplet, Activity, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";

type TempPayload = {
  ts: number | null;
  kombi: { temp_c: number | null; hum_pct: number | null };
  garaza: { temp_c: number | null; hum_pct: number | null };
};

type GpsPayload = {
  ts: number | null;
  lat: number | null;
  lon: number | null;
  speed_kmh: number | null;
  course: number | null;
  altitude_m: number | null;
  satellites?: number | null;
  ok: boolean;
  error: string | null;
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
  if (t == null) return "border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50";
  if (t < 8) return "border-sky-500/30 bg-gradient-to-br from-sky-950/30 to-sky-900/20";
  if (t < 16) return "border-emerald-500/30 bg-gradient-to-br from-emerald-950/30 to-emerald-900/20";
  if (t < 24) return "border-amber-500/30 bg-gradient-to-br from-amber-950/30 to-amber-900/20";
  return "border-red-500/30 bg-gradient-to-br from-red-950/30 to-red-900/20";
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

    const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    });

    tileLayer.on("tileerror", (error, tile) => {
      console.error("[GpsMiniMap] Tile load error:", {
        error,
        url: tile.src,
        tile: tile,
      });
    });

    tileLayer.addTo(map);

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

    setTimeout(() => {
      map.setView([lat, lon], 14);
      map.invalidateSize();

      if (!markerRef.current) {
        markerRef.current = L.circleMarker([lat, lon], { radius: 6, color: "#3b82f6", fillColor: "#3b82f6", fillOpacity: 0.8 });
        markerRef.current.addTo(map);
      } else {
        markerRef.current.setLatLng([lat, lon]);
      }
    }, 100);
  }, [lat, lon]);

  return <div ref={elRef} className="h-32 w-full rounded-xl overflow-hidden border border-zinc-800/50" />;
}

function GpsTrackMap({ data }: { data: TrackPayload | null }) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    if (mapRef.current) return;

    const map = L.map(elRef.current, { zoomControl: true, attributionControl: true }).setView([43.8563, 18.4131], 9);

    const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    });

    tileLayer.on("tileerror", (error, tile) => {
      console.error("[GpsTrackMap] Tile load error:", {
        error,
        url: tile.src,
        tile: tile,
      });
    });

    tileLayer.addTo(map);

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
    const poly = L.polyline(latlngs, { weight: 4, color: "#3b82f6" });
    poly.addTo(layer);

    const last = pts[pts.length - 1];
    L.circleMarker([last.lat, last.lon], { radius: 7, color: "#3b82f6", fillColor: "#3b82f6", fillOpacity: 0.8 }).addTo(layer);

    map.fitBounds(poly.getBounds(), { padding: [20, 20] });
  }, [data]);

  return <div ref={elRef} className="h-[420px] w-full rounded-xl overflow-hidden border border-zinc-800/50" />;
}

export default function OverviewDashboard() {
  const [track, setTrack] = useState<TrackPayload | null>(null);

  // GPS current data with React Query (polls every 60s, keeps previous data)
  const { data: gpsData } = useQuery({
    queryKey: ["gps", "current"],
    queryFn: async () => {
      const r = await apiFetch("/api/gps/current", { cache: "no-store" });
      if (!r.ok) throw new Error(`GPS API returned ${r.status}`);
      return (await r.json()) as GpsPayload;
    },
    refetchInterval: 60000, // Poll every 60 seconds (1 minute)
    placeholderData: (previousData) => previousData, // keepPreviousData equivalent
    retry: 1,
  });

  const gps = gpsData ?? null;

  // Temperature data with React Query (polls every 2s, keeps previous data)
  const { data: tempData } = useQuery({
    queryKey: ["temperature", "latest"],
    queryFn: async () => {
      const r = await apiFetch("/api/temperature/latest", { cache: "no-store" });
      if (!r.ok) throw new Error(`Temperature API returned ${r.status}`);
      return (await r.json()) as {
        ts: number;
        sensors: Array<{
          sensor_index: number;
          pin: number;
          temperature_c: number | null;
          humidity: number | null;
          ok: boolean;
          error: string | null;
        }>;
      };
    },
    refetchInterval: 2000, // Poll every 2 seconds
    placeholderData: (previousData) => previousData, // keepPreviousData equivalent
    retry: 1,
  });

  // Transform temperature data
  const temps = useMemo<TempPayload | null>(() => {
    if (!tempData) return null;

    const raw = tempData;
    if (!raw.sensors || raw.sensors.length === 0) {
      return {
        ts: raw.ts ?? null,
        kombi: { temp_c: null, hum_pct: null },
        garaza: { temp_c: null, hum_pct: null },
      };
    }

    const s0 = raw.sensors.find((s) => s.sensor_index === 0) ?? raw.sensors[0] ?? null;
    const s1 = raw.sensors.find((s) => s.sensor_index === 1) ?? (raw.sensors.length > 1 ? raw.sensors[1] : null) ?? null;

    return {
      ts: raw.ts ?? null,
      kombi: {
        temp_c: s0?.temperature_c ?? null,
        hum_pct: s0?.humidity ?? null,
      },
      garaza: {
        temp_c: s1?.temperature_c ?? null,
        hum_pct: s1?.humidity ?? null,
      },
    };
  }, [tempData]);


  // GPS track (24h)
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch("/api/gps/track?hours=24", { cache: "no-store" });
        if (!r.ok) return;

        const raw = (await r.json()) as {
          since: number;
          now: number;
          rows: Array<{ ts: number; lat: number | null; lon: number | null; speed_kmh: number | null; course: number | null; altitude_m: number | null }>;
        };

        // Transform backend format to component format
        const transformed: TrackPayload = {
          hours: 24,
          count: raw.rows.length,
          points: raw.rows
            .filter((p) => p.lat != null && p.lon != null)
            .map((p) => ({
              ts: new Date(p.ts * 1000).toISOString(),
              lat: p.lat!,
              lon: p.lon!,
              speed_m_s: p.speed_kmh != null ? p.speed_kmh / 3.6 : null,
            })),
        };

        if (alive) setTrack(transformed);
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
  const speedKmh = useMemo(() => gps?.speed_kmh ?? null, [gps?.speed_kmh]);

  const kombiT = temps?.kombi?.temp_c ?? null;

  const gpsStatus = gps?.ok === false ? "Disconnected" : gpsHasFix ? "Fix" : "No fix";

  // Reverse geocoding for address
  const { data: address } = useQuery({
    queryKey: ["address", gps?.lat, gps?.lon],
    queryFn: async () => {
      if (!gpsHasFix || !gps?.lat || !gps?.lon) return null;
      try {
        const response = await fetch(
          `https://nominatim.openstreetmap.org/reverse?format=json&lat=${gps.lat}&lon=${gps.lon}&zoom=16&addressdetails=1`,
          {
            headers: {
              "User-Agent": "Smartify-Dashboard/1.0",
            },
          }
        );
        if (!response.ok) return null;
        const data = await response.json();
        const addr = data.address;
        if (!addr) return null;
        
        const parts = [];
        if (addr.road) parts.push(addr.road);
        if (addr.house_number) parts.push(addr.house_number);
        if (addr.village || addr.town || addr.city) {
          parts.push(addr.village || addr.town || addr.city);
        }
        if (addr.country) parts.push(addr.country);
        
        return parts.length > 0 ? parts.join(", ") : data.display_name || null;
      } catch {
        return null;
      }
    },
    enabled: gpsHasFix && !!gps?.lat && !!gps?.lon,
    staleTime: 60000, // Cache for 1 minute (addresses don't change quickly)
    retry: 1,
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard Overview</h1>
          <p className="text-sm text-zinc-400 mt-1">Real-time monitoring of your van systems</p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {/* GPS Location Card */}
        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                  <MapPin className="h-4 w-4 text-blue-400" />
                </div>
                Van Location
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 relative z-10">
            <GpsMiniMap lat={gps?.lat ?? null} lon={gps?.lon ?? null} />

            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">Status</span>
                <span className={`font-semibold ${gpsHasFix ? "text-emerald-400" : "text-amber-400"}`}>
                  {gpsStatus}
                </span>
              </div>

              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400">Location</span>
                <span className="font-medium text-xs text-right max-w-[60%] truncate text-zinc-300" title={address || undefined}>
                  {gpsHasFix ? (address || `${gps?.lat?.toFixed(4)}, ${gps?.lon?.toFixed(4)}`) : "—"}
                </span>
              </div>

              <div className="flex items-center justify-between text-sm">
                <span className="text-zinc-400 flex items-center gap-2">
                  <Navigation className="h-3.5 w-3.5" />
                  Speed
                </span>
                <span className="font-semibold tabular-nums text-zinc-200">
                  {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Temperature + Water Stacked */}
        <div className="flex flex-col gap-6">
          {/* Temperature Card */}
          <Card className={`group relative overflow-hidden border shadow-lg transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20 flex-1 ${tempClass(kombiT)}`}>
            <div className="absolute inset-0 bg-gradient-to-br from-amber-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <CardContent className="flex flex-col space-y-3 py-4 relative z-10">
              {import.meta.env.DEV && (
                <div className="text-xs text-blue-400 p-1.5 bg-blue-950/50 rounded-lg border border-blue-800/30 mb-1">
                  <strong>Debug:</strong> temps = {temps ? JSON.stringify(temps, null, 2) : 'null'}
                </div>
              )}
              
              <div className="flex items-center justify-between rounded-lg bg-blue-500/10 border border-blue-500/30 px-4 py-3 backdrop-blur-sm transition-all hover:bg-blue-500/15">
                <span className="flex items-center gap-2.5 text-zinc-300">
                  <Car className="h-4 w-4 text-blue-400" />
                  <span className="font-medium">Kombi</span>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-bold tabular-nums text-lg text-blue-300">
                    {formatTemp(temps?.kombi?.temp_c ?? null)}
                  </span>
                  <span className="text-xs text-zinc-400">{formatHum(temps?.kombi?.hum_pct ?? null)}</span>
                </div>
              </div>

              <div className="flex items-center justify-between rounded-lg bg-amber-500/10 border border-amber-500/30 px-4 py-3 backdrop-blur-sm transition-all hover:bg-amber-500/15">
                <span className="flex items-center gap-2.5 text-zinc-300">
                  <Warehouse className="h-4 w-4 text-amber-400" />
                  <span className="font-medium">Garaža</span>
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-bold tabular-nums text-lg text-amber-300">
                    {formatTemp(temps?.garaza?.temp_c ?? null)}
                  </span>
                  <span className="text-xs text-zinc-400">{formatHum(temps?.garaza?.hum_pct ?? null)}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Water Level Card */}
          <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-blue-950/30 to-blue-900/20 backdrop-blur-sm transition-all duration-300 hover:border-blue-700/50 hover:shadow-xl hover:shadow-blue-900/20 flex-1">
            <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
            <CardHeader className="pb-3 relative z-10">
              <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
                <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                  <Droplet className="h-4 w-4 text-blue-400" />
                </div>
                Water Level
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm py-2 relative z-10">
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Level</span>
                <span className="font-semibold text-zinc-200">— %</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-zinc-400">Status</span>
                <span className="font-semibold text-zinc-200">—</span>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Battery Card */}
        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                <Battery className="h-4 w-4 text-emerald-400" />
              </div>
              Battery
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 relative z-10">
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">State of charge</span>
              <span className="font-semibold text-zinc-200">— %</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">Voltage</span>
              <span className="font-semibold text-zinc-200">— V</span>
            </div>
          </CardContent>
        </Card>

        {/* Heater Card */}
        <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
          <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
          <CardHeader className="pb-3 relative z-10">
            <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
              <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/20">
                <Power className="h-4 w-4 text-orange-400" />
              </div>
              Heater
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 relative z-10">
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">Status</span>
              <span className="font-semibold text-zinc-200">—</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-zinc-400">Mode</span>
              <span className="font-semibold text-zinc-200">—</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* GPS Map Section */}
      <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20">
        <div className="absolute inset-0 bg-gradient-to-br from-blue-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
        <CardHeader className="pb-4 relative z-10">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg font-semibold text-zinc-200">GPS Map & Track</CardTitle>
              <p className="text-sm text-zinc-400 mt-1">Last 24 hours location history</p>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-800/50 border border-zinc-700/50">
              <Activity className="h-4 w-4 text-blue-400" />
              <span className="text-xs font-medium text-zinc-300">Live</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 relative z-10">
          <GpsTrackMap data={track} />

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Track Points</span>
                <span className="font-bold text-lg tabular-nums text-zinc-200">{track?.count ?? 0}</span>
              </div>
            </div>
            <div className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">Current Speed</span>
                <span className="font-bold text-lg tabular-nums text-zinc-200">
                  {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
                </span>
              </div>
            </div>
            <div className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-400">GPS Status</span>
                <span className={`font-bold text-lg ${gpsHasFix ? "text-emerald-400" : "text-amber-400"}`}>
                  {gpsStatus}
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
