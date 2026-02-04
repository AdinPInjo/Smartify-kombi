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
    <Card className="glass-card p-0">
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-base">Recent points</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 px-4 pb-4 pt-0">
        {isLoading && safePoints.length === 0 ? (
          <div className="text-sm text-muted-foreground">Loading…</div>
        ) : last10.length === 0 ? (
          <div className="text-sm text-muted-foreground">No points yet.</div>
        ) : (
          <div className="space-y-1">
            {last10.map((p, idx) => (
              <div
                key={`${p.ts}-${idx}`}
                className="flex items-center justify-between text-xs rounded-md border border-glass bg-secondary/30 px-2 py-1"
              >
                <span className="text-muted-foreground">{p.ts}</span>
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
