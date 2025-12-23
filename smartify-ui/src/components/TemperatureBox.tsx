import { useEffect, useMemo, useState } from "react";
import { Thermometer, Warehouse, Camper } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiFetch } from "@/lib/utils";

type TempPayload = {
  ts: number | null;
  kombi: { temp_c: number | null; hum_pct: number | null };
  garaza: { temp_c: number | null; hum_pct: number | null };
};

function tempClass(t: number | null) {
  if (t == null) return "border-zinc-700 bg-zinc-900/40";
  if (t < 8) return "border-sky-500/40 bg-sky-500/10";
  if (t < 16) return "border-emerald-500/40 bg-emerald-500/10";
  if (t < 24) return "border-amber-500/40 bg-amber-500/10";
  return "border-red-500/40 bg-red-500/10";
}

function formatTemp(t: number | null) {
  return t == null ? "—" : `${t.toFixed(1)}°C`;
}
function formatHum(h: number | null) {
  return h == null ? "" : `${h.toFixed(0)}%`;
}

export default function TemperatureBox() {
  const [data, setData] = useState<TempPayload | null>(null);

  useEffect(() => {
    let alive = true;

    const tick = async () => {
      try {
        const r = await apiFetch("/api/temperature/latest", { cache: "no-store" });
        if (!r.ok) return;

        const raw = (await r.json()) as {
          ts: number;
          sensors: { sensor_index: number; temperature_c: number | null; humidity: number | null }[];
        };

        const s0 = raw.sensors.find((s) => s.sensor_index === 0) ?? raw.sensors[0];
        const s1 = raw.sensors.find((s) => s.sensor_index === 1) ?? raw.sensors[1];

        const mapped: TempPayload = {
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

        if (alive) setData(mapped);
      } catch {
        // ignore
      }
    };

    tick();
    const id = setInterval(tick, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const kombiT = data?.kombi?.temp_c ?? null;

  const tsLabel = useMemo(() => {
    if (!data?.ts) return "—";
    return new Date(data.ts * 1000).toLocaleTimeString();
  }, [data?.ts]);

  return (
    <Card className={`rounded-2xl border shadow-sm ${tempClass(kombiT)}`}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Thermometer className="h-5 w-5" />
            Temperature
          </CardTitle>
          <div className="text-xs text-zinc-400">{tsLabel}</div>
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        <div className="grid gap-3">
          {/* Kombi */}
          <div className="flex items-center justify-between rounded-xl bg-black/20 px-3 py-2">
            <div className="flex items-center gap-2">
              <Camper className="h-4 w-4" />
              <div className="text-sm">Kombi</div>
            </div>
            <div className="text-sm font-semibold tabular-nums">
              {formatTemp(data?.kombi?.temp_c ?? null)}
              <span className="ml-2 text-xs text-zinc-400">
                {formatHum(data?.kombi?.hum_pct ?? null)}
              </span>
            </div>
          </div>

          {/* Garaža */}
          <div className="flex items-center justify-between rounded-xl bg-black/20 px-3 py-2">
            <div className="flex items-center gap-2">
              <Warehouse className="h-4 w-4" />
              <div className="text-sm">Garaža</div>
            </div>
            <div className="text-sm font-semibold tabular-nums">
              {formatTemp(data?.garaza?.temp_c ?? null)}
              <span className="ml-2 text-xs text-zinc-400">
                {formatHum(data?.garaza?.hum_pct ?? null)}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
