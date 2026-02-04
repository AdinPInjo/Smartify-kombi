import { useQuery } from "@tanstack/react-query";
import { Map, Mountain } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/utils";

type PeriodStats = {
  since: number;
  distance_km: number;
  altitude_min_m: number | null;
  altitude_max_m: number | null;
  altitude_avg_m: number | null;
  points: number;
};

type SummaryPayload = {
  now: number;
  periods: {
    week: PeriodStats;
    month: PeriodStats;
    year: PeriodStats;
    total: PeriodStats;
  };
};

const formatKm = (km: number | null | undefined) => {
  if (km == null) return "—";
  if (km < 1) return `${(km * 1000).toFixed(0)} m`;
  return `${km.toFixed(1)} km`;
};

const formatAlt = (m: number | null | undefined) => {
  if (m == null) return "—";
  return `${m.toFixed(1)} m`;
};

const GpsStatsCard = () => {
  const { data } = useQuery({
    queryKey: ["gps", "stats", "summary"],
    queryFn: async () => {
      const r = await apiFetch("/api/gps/stats/summary", { cache: "no-store" });
      if (!r.ok) throw new Error(`GPS stats API returned ${r.status}`);
      return (await r.json()) as SummaryPayload;
    },
    refetchInterval: 60000,
    retry: 1,
  });

  const stats = data?.periods;

  return (
    <Card className="glass-card p-0">
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <Map className="w-4 h-4 text-primary" />
          </div>
          Distance Summary
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pb-4 pt-0">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-secondary/30 border border-glass p-3">
            <p className="metric-label">Week</p>
            <p className="text-lg font-semibold">{formatKm(stats?.week?.distance_km)}</p>
          </div>
          <div className="rounded-xl bg-secondary/30 border border-glass p-3">
            <p className="metric-label">Month</p>
            <p className="text-lg font-semibold">{formatKm(stats?.month?.distance_km)}</p>
          </div>
          <div className="rounded-xl bg-secondary/30 border border-glass p-3">
            <p className="metric-label">Year</p>
            <p className="text-lg font-semibold">{formatKm(stats?.year?.distance_km)}</p>
          </div>
          <div className="rounded-xl bg-secondary/30 border border-glass p-3">
            <p className="metric-label">Total</p>
            <p className="text-lg font-semibold">{formatKm(stats?.total?.distance_km)}</p>
          </div>
        </div>

        <div className="rounded-xl bg-secondary/30 border border-glass p-3">
          <div className="flex items-center gap-2 mb-2">
            <Mountain className="w-4 h-4 text-primary" />
            <span className="text-sm font-medium">Altitude (latest period)</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <p className="metric-label">Min</p>
              <p className="font-semibold">{formatAlt(stats?.week?.altitude_min_m)}</p>
            </div>
            <div>
              <p className="metric-label">Avg</p>
              <p className="font-semibold">{formatAlt(stats?.week?.altitude_avg_m)}</p>
            </div>
            <div>
              <p className="metric-label">Max</p>
              <p className="font-semibold">{formatAlt(stats?.week?.altitude_max_m)}</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export default GpsStatsCard;
