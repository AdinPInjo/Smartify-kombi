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
import { Thermometer, TrendingUp } from "lucide-react";

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <Thermometer className="h-6 w-6 text-amber-400" />
            </div>
            Temperature History
          </h1>
          <p className="text-sm text-zinc-400 mt-2">Kombi + Garaža sensor readings over time</p>
        </div>

        <div className="flex gap-2">
          {(["day", "week", "month", "year"] as Range[]).map((r) => (
            <Button
              key={r}
              variant={range === r ? "default" : "outline"}
              size="sm"
              onClick={() => setRange(r)}
              className={
                range === r
                  ? "bg-blue-500 hover:bg-blue-600 text-white border-blue-500"
                  : "bg-zinc-800/50 hover:bg-zinc-700/50 border-zinc-700/50 text-zinc-300"
              }
            >
              {r.charAt(0).toUpperCase() + r.slice(1)}
            </Button>
          ))}
        </div>
      </div>

      {/* Chart Card */}
      <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20">
        <div className="absolute inset-0 bg-gradient-to-br from-amber-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
        <CardHeader className="pb-4 relative z-10">
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg font-semibold text-zinc-200 flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-amber-400" />
              Temperature Oscillations
            </CardTitle>
            <div className="text-xs text-zinc-400">
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
                    backgroundColor: "#18181b", 
                    border: "1px solid #3f3f46",
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
