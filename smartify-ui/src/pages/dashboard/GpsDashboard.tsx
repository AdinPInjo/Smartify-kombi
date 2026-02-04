import { useMemo } from "react";
import { MapPin, Gauge, Satellite, Route, AlertCircle } from "lucide-react";
import { useGpsData } from "@/hooks/useGpsData";
import GpsMap from "@/components/gps/GpsMap";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { Alert, AlertDescription } from "@/components/ui/alert";

const GpsDashboard = () => {
  const trackMinutes = 1440;
  const { currentData, uiCurrentData, trackData, isLoadingCurrent, isLoadingTrack, error } =
    useGpsData(trackMinutes);

  // Use smoothed for UI when available, fallback to raw
  const displayData = uiCurrentData ?? currentData;

  const fitKey = useMemo(() => `minutes:${trackMinutes}`, [trackMinutes]);

  const { data: summary } = useQuery({
    queryKey: ["gps", "stats", "summary"],
    queryFn: async () => {
      const r = await apiFetch("/api/gps/stats/summary", { cache: "no-store" });
      if (!r.ok) throw new Error(`GPS stats API returned ${r.status}`);
      return (await r.json()) as {
        periods: {
          day: { distance_km: number };
          week: { distance_km: number };
          month: { distance_km: number };
          year: { distance_km: number };
          total: { distance_km: number };
        };
      };
    },
    refetchInterval: 60000,
    retry: 1,
  });

  const speedKmh = displayData ? displayData.speed_m_s * 3.6 : null;
  const speeds = trackData.map((p) => p.speed_kmh).filter((v): v is number => v != null);
  const maxSpeed = speeds.length ? Math.max(...speeds) : null;
  const avgSpeed = speeds.length ? speeds.reduce((s, v) => s + v, 0) / speeds.length : null;

  const formatKm = (km: number | null | undefined) => {
    if (km == null) return "—";
    if (km < 1) return `${(km * 1000).toFixed(0)} m`;
    return `${km.toFixed(1)} km`;
  };

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
        {/* Map */}
        <Card className="glass-card p-0 lg:col-span-2 lg:row-span-2">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <MapPin className="w-4 h-4 text-primary" />
              </div>
              Live Map
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            <div className="relative h-96 rounded-xl bg-secondary/30 overflow-hidden border border-glass">
              <GpsMap
                currentData={displayData}
                trackData={trackData}
                isLoading={isLoadingTrack}
                fitKey={fitKey}
                className="h-96 border-0 rounded-lg"
              />
              <div className="absolute bottom-4 left-4 glass-card-static p-3 rounded-xl">
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <p className="text-muted-foreground">Lat</p>
                    <p className="font-mono font-bold">
                      {displayData ? `${displayData.lat.toFixed(4)}°` : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-muted-foreground">Long</p>
                    <p className="font-mono font-bold">
                      {displayData ? `${displayData.lon.toFixed(4)}°` : "—"}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Status */}
        <Card className="glass-card p-0">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <Satellite className="w-4 h-4 text-primary" />
              </div>
              Signal Status
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 px-4 pb-4 pt-0">
            <div className="flex items-center justify-between p-3 rounded-xl bg-secondary/30 border border-glass">
              <span className="text-muted-foreground">GPS Lock</span>
              <div className="flex items-center gap-2">
                <span className={displayData?.mode && displayData.mode >= 2 ? "status-dot-online" : "status-dot-warning"} />
                <span className="text-success font-medium">
                  {displayData?.mode && displayData.mode >= 2 ? "3D Fix" : "No Fix"}
                </span>
              </div>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-secondary/30 border border-glass">
              <span className="text-muted-foreground">Satellites</span>
              <span className="font-bold text-primary">
                {displayData?.satellites != null ? displayData.satellites : "—"}
              </span>
            </div>

            <div className="flex items-center justify-between p-3 rounded-xl bg-secondary/30 border border-glass">
              <span className="text-muted-foreground">Altitude</span>
              <span className="font-bold">
                {displayData?.altitude_m != null ? `${displayData.altitude_m.toFixed(1)} m` : "—"}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Speed */}
        <Card className="glass-card p-0">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <Gauge className="w-4 h-4 text-primary" />
              </div>
              Speed
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            <div className="text-center py-4">
              <span className="text-6xl font-bold text-primary glow-text">
                {speedKmh == null ? "—" : speedKmh.toFixed(1)}
              </span>
              <span className="text-2xl text-muted-foreground ml-2">km/h</span>
            </div>
            <div className="grid grid-cols-2 gap-4 mt-4">
              <div className="text-center p-3 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Max Today</p>
                <p className="text-xl font-bold">{maxSpeed == null ? "—" : `${maxSpeed.toFixed(1)} km/h`}</p>
              </div>
              <div className="text-center p-3 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Avg</p>
                <p className="text-xl font-bold">{avgSpeed == null ? "—" : `${avgSpeed.toFixed(1)} km/h`}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Trip Stats */}
        <Card className="glass-card p-0 lg:col-span-3">
          <CardHeader className="pb-2 px-4 pt-4">
            <CardTitle className="text-base font-medium flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <Route className="w-4 h-4 text-primary" />
              </div>
              Trip Statistics
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 pt-0">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="text-center p-4 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Today</p>
                <p className="text-2xl font-bold text-primary">{formatKm(summary?.periods.day?.distance_km)}</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">This Week</p>
                <p className="text-2xl font-bold">{formatKm(summary?.periods.week?.distance_km)}</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">This Month</p>
                <p className="text-2xl font-bold">{formatKm(summary?.periods.month?.distance_km)}</p>
              </div>
              <div className="text-center p-4 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Total</p>
                <p className="text-2xl font-bold">{formatKm(summary?.periods.total?.distance_km)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default GpsDashboard;
