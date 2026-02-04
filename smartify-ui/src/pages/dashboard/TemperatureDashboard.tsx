import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/utils";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from "recharts";
import { Thermometer, TrendingUp, TrendingDown, Minus, Clock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

type Range = "day" | "week" | "month" | "year";

type BackendRow = {
  ts: number;
  sensor_index: number;
  temperature_c: number | null;
  humidity: number | null;
};

type BackendPayload = {
  since: number;
  now: number;
  rows: BackendRow[];
  bucket_seconds?: number;
};

function formatTs(ts: number, range: Range) {
  const d = new Date(ts * 1000);
  if (range === "day") return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (range === "week") return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
  if (range === "month") return d.toLocaleDateString([], { month: "short", day: "2-digit" });
  return d.toLocaleDateString([], { year: "numeric", month: "short" });
}

export default function TemperatureDashboard() {
  const [range, setRange] = useState<Range>("day");
  const [data, setData] = useState<BackendPayload | null>(null);

  const { data: weather } = useQuery({
    queryKey: ["weather", "current"],
    queryFn: async () => {
      const r = await apiFetch("/api/weather/current", { cache: "no-store" });
      if (!r.ok) throw new Error(`Weather API returned ${r.status}`);
      return (await r.json()) as {
        ok: boolean;
        temp_c: number | null;
        wind_kmh: number | null;
        weather_code: number | null;
        ts: number | null;
        error: string | null;
      };
    },
    refetchInterval: 60000,
    retry: 1,
  });

  const { data: snapshot } = useQuery({
    queryKey: ["temperature", "snapshot", "latest"],
    queryFn: async () => {
      const r = await apiFetch("/api/temperature/snapshot/latest", { cache: "no-store" });
      if (!r.ok) throw new Error(`Snapshot API returned ${r.status}`);
      return (await r.json()) as {
        ts: number | null;
        sensors: Array<{
          sensor_index: number;
          sensor_name?: string | null;
          avg_temp: number | null;
          avg_humidity: number | null;
        }>;
      };
    },
    refetchInterval: 5000,
    retry: 1,
  });

  useEffect(() => {
    let alive = true;

    const load = async () => {
      if (alive) setData(null);
      
      try {
        const r = await apiFetch(`/api/temperature/history?range=${range}`, { cache: "no-store" });
        if (!r.ok) {
          console.warn(`[TemperatureDashboard] API returned status ${r.status} for range ${range}`);
          return;
        }
        const j = (await r.json()) as BackendPayload;
        if (alive) {
          setData(j);
          console.log(`[TemperatureDashboard] Loaded ${j.rows?.length ?? 0} rows for range ${range}`, {
            since: j.since,
            now: j.now,
            timeSpan: j.now - j.since,
          });
        }
      } catch (err) {
        console.error(`[TemperatureDashboard] Failed to load data for range ${range}:`, err);
      }
    };

    load();
    return () => {
      alive = false;
    };
  }, [range]);

  const chartData = useMemo(() => {
    const rows = data?.rows ?? [];
    const byTs = new Map<number, { ts: number; kombi: number | null; garaza: number | null }>();

    for (const r of rows) {
      if (!byTs.has(r.ts)) {
        byTs.set(r.ts, { ts: r.ts, kombi: null, garaza: null });
      }
      const entry = byTs.get(r.ts)!;
      if (r.sensor_index === 0) {
        entry.kombi = r.temperature_c;
      } else if (r.sensor_index === 1) {
        entry.garaza = r.temperature_c;
      }
    }

    const series = Array.from(byTs.values()).sort((a, b) => a.ts - b.ts);

    return series.map((p) => ({
      ...p,
      label: formatTs(p.ts, range),
    }));
  }, [data, range]);

  const kombiSeries = useMemo(
    () => chartData.map((p) => p.kombi).filter((v) => v != null) as number[],
    [chartData]
  );
  const garazaSeries = useMemo(
    () => chartData.map((p) => p.garaza).filter((v) => v != null) as number[],
    [chartData]
  );

  const kombiMin = kombiSeries.length ? Math.min(...kombiSeries) : null;
  const kombiMax = kombiSeries.length ? Math.max(...kombiSeries) : null;
  const garazaMin = garazaSeries.length ? Math.min(...garazaSeries) : null;
  const garazaMax = garazaSeries.length ? Math.max(...garazaSeries) : null;

  const snapshotKombi = snapshot?.sensors?.find((s) => s.sensor_index === 0 || s.sensor_name === "kombi") ?? null;
  const snapshotGaraza = snapshot?.sensors?.find((s) => s.sensor_index === 1 || s.sensor_name === "garaza") ?? null;

  const kombiNow = snapshotKombi?.avg_temp ?? null;
  const garazaNow = snapshotGaraza?.avg_temp ?? null;
  const outsideNow = weather?.ok ? weather?.temp_c ?? null : null;

  const getTrend = (series: number[]) => {
    if (series.length < 2) return "stable";
    const last = series[series.length - 1]!;
    const prev = series[series.length - 2]!;
    if (last > prev) return "up";
    if (last < prev) return "down";
    return "stable";
  };

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case "up":
        return <TrendingUp className="w-4 h-4 text-warning" />;
      case "down":
        return <TrendingDown className="w-4 h-4 text-primary" />;
      default:
        return <Minus className="w-4 h-4 text-muted-foreground" />;
    }
  };

  const getTemperatureColor = (temp: number | null) => {
    if (temp == null) return "text-muted-foreground";
    if (temp > 25) return "text-destructive";
    if (temp < 15) return "text-primary";
    return "text-success";
  };

  const spark = (series: number[]) => {
    if (!series.length) return Array.from({ length: 6 }, () => null);
    const slice = series.slice(-6);
    return slice.length >= 6 ? slice : Array.from({ length: 6 - slice.length }, () => null).concat(slice);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <Thermometer className="h-6 w-6 text-primary icon-glow" />
            </div>
            Temperature History
          </h1>
          <p className="text-sm text-muted-foreground mt-2">Kombi + Garaža sensor readings over time</p>
        </div>

        <div className="flex gap-2">
          {(["day", "week", "month", "year"] as Range[]).map((r) => (
            <Button
              key={r}
              variant={range === r ? "default" : "outline"}
              size="sm"
              onClick={() => setRange(r)}
            >
              {r.charAt(0).toUpperCase() + r.slice(1)}
            </Button>
          ))}
        </div>
      </div>

      {/* Current Readings */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 lg:gap-6">
        {[
          {
            id: "kombi",
            name: "Kombi Interior",
            location: "Main cabin",
            current: kombiNow,
            min: kombiMin,
            max: kombiMax,
            trend: getTrend(kombiSeries),
            history: spark(kombiSeries),
          },
          {
            id: "garaza",
            name: "Garage",
            location: "Rear storage",
            current: garazaNow,
            min: garazaMin,
            max: garazaMax,
            trend: getTrend(garazaSeries),
            history: spark(garazaSeries),
          },
          {
            id: "outside",
            name: "Outside",
            location: "GPS weather",
            current: outsideNow,
            min: null,
            max: null,
            trend: "stable",
            history: Array.from({ length: 6 }, () => null),
          },
        ].map((sensor) => (
          <Card key={sensor.id} className="glass-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                  <Thermometer className="h-4 w-4 text-primary" />
                </div>
                {sensor.name}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-end justify-between">
                <div>
                  <span className={`text-4xl font-bold ${getTemperatureColor(sensor.current)}`}>
                    {sensor.current != null ? sensor.current.toFixed(1) : "—"}
                  </span>
                  <span className="text-xl text-muted-foreground">°C</span>
                </div>
                {getTrendIcon(sensor.trend)}
              </div>

              <p className="text-sm text-muted-foreground">{sensor.location}</p>

              <div className="h-12 flex items-end gap-1">
                {sensor.history.map((val, i) => (
                  <div
                    key={i}
                    className="flex-1 bg-primary/40 rounded-t"
                    style={{ height: val == null ? "15%" : `${Math.max(15, ((val - 10) / 20) * 100)}%` }}
                  />
                ))}
              </div>

              <div className="grid grid-cols-2 gap-4 pt-2 border-t border-glass">
                <div>
                  <p className="metric-label">Min</p>
                  <p className="font-semibold">{sensor.min != null ? `${sensor.min.toFixed(1)}°C` : "—"}</p>
                </div>
                <div>
                  <p className="metric-label">Max</p>
                  <p className="font-semibold">{sensor.max != null ? `${sensor.max.toFixed(1)}°C` : "—"}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Chart Card */}
      <Card className="glass-card">
        <CardHeader className="pb-4 relative z-10">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold text-foreground flex items-center gap-2">
              <Clock className="h-5 w-5 text-primary" />
              History
            </CardTitle>
            <div className="text-xs text-muted-foreground">
              {data?.rows?.length ?? 0} data points
            </div>
          </div>
        </CardHeader>
        <CardContent className="relative z-10">
          <div className="h-[400px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart 
                key={range} 
                data={chartData}
                margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#3f3f46" opacity={0.3} />
                <XAxis 
                  dataKey="label" 
                  minTickGap={range === "day" ? 20 : range === "week" ? 30 : range === "month" ? 40 : 50}
                  angle={range === "year" ? -45 : 0}
                  textAnchor={range === "year" ? "end" : "middle"}
                  height={range === "year" ? 60 : 30}
                  stroke="#71717a"
                  style={{ fontSize: "12px" }}
                />
                <YAxis 
                  domain={["auto", "auto"]} 
                  stroke="#71717a"
                  style={{ fontSize: "12px" }}
                />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: "rgba(15, 23, 42, 0.9)", 
                    border: "1px solid rgba(148, 163, 184, 0.2)",
                    borderRadius: "8px",
                    color: "#e4e4e7"
                  }}
                />
                <Legend 
                  wrapperStyle={{ paddingTop: "20px" }}
                  iconType="line"
                />
                <Line 
                  type="monotone" 
                  dataKey="kombi" 
                  name="Kombi (°C)" 
                  dot={false} 
                  stroke="#3b82f6" 
                  strokeWidth={2.5}
                  connectNulls={false}
                />
                <Line 
                  type="monotone" 
                  dataKey="garaza" 
                  name="Garaža (°C)" 
                  dot={false} 
                  stroke="#f59e0b" 
                  strokeWidth={2.5}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
