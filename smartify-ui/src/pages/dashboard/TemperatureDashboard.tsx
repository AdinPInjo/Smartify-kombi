import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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

type Payload = {
  range: Range;
  bucket_s: number;
  count: number;
  series: Array<{ ts: number; kombi: number | null; garaza: number | null }>;
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
  const [data, setData] = useState<Payload | null>(null);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      const r = await fetch(`/api/temperature/history?range=${range}`, { cache: "no-store" });
      if (!r.ok) return;
      const j = (await r.json()) as Payload;
      if (alive) setData(j);
    };

    load();
    return () => {
      alive = false;
    };
  }, [range]);

  const chartData = useMemo(() => {
    const series = data?.series ?? [];
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
            {data?.count ?? 0} points • bucket {data?.bucket_s ?? 0}s
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
