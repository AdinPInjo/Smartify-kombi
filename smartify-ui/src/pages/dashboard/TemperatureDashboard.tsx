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
      const r = await apiFetch(`/api/temperature/history?range=${range}`, { cache: "no-store" });
      if (!r.ok) return;
      const j = (await r.json()) as BackendPayload;
      if (alive) setData(j);
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
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xl font-semibold">Temperature</div>
          <div className="text-sm opacity-70">Kombi + Garaža history</div>
        </div>

        <div className="flex gap-2">
          {(["day", "week", "month", "year"] as Range[]).map((r) => (
            <Button
              key={r}
              variant={range === r ? "default" : "outline"}
              size="sm"
              onClick={() => setRange(r)}
            >
              {r}
            </Button>
          ))}
        </div>
      </div>

      <Card className="rounded-2xl">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Temperature oscillations</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[360px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" minTickGap={20} />
                <YAxis domain={["auto", "auto"]} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="kombi" name="Kombi (°C)" dot={false} />
                <Line type="monotone" dataKey="garaza" name="Garaža (°C)" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-3 text-xs opacity-70">
            {data?.rows?.length ?? 0} points
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
