import type { GpsTrackPoint } from "@/hooks/useGpsData";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type Props = {
  points?: GpsTrackPoint[];   // make optional
  isLoading?: boolean;
};

const RecentPointsTable = ({ points, isLoading }: Props) => {
  const safePoints: GpsTrackPoint[] = Array.isArray(points) ? points : [];
  const last10 = safePoints.slice(-10).reverse();

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Recent points</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && safePoints.length === 0 ? (
          <div className="text-sm opacity-70">Loading…</div>
        ) : last10.length === 0 ? (
          <div className="text-sm opacity-70">No points yet.</div>
        ) : (
          <div className="space-y-1">
            {last10.map((p, idx) => (
              <div
                key={`${p.ts}-${idx}`}
                className="flex items-center justify-between text-xs rounded-md border px-2 py-1"
              >
                <span className="opacity-80">{p.ts}</span>
                <span className="tabular-nums">
                  {p.lat.toFixed(6)}, {p.lon.toFixed(6)}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default RecentPointsTable;
