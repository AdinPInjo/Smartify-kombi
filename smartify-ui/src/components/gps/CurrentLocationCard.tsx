import { MapPin, Clock, Gauge, Satellite, Mountain } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { GpsCurrentData } from "@/hooks/useGpsData";
import { cn } from "@/lib/utils";

interface CurrentLocationCardProps {
  data: GpsCurrentData | null;
  isLoading: boolean;
}

const CurrentLocationCard = ({ data, isLoading }: CurrentLocationCardProps) => {
  const formatCoordinate = (value: number, isLat: boolean) => {
    const direction = isLat ? (value >= 0 ? "N" : "S") : (value >= 0 ? "E" : "W");
    return `${Math.abs(value).toFixed(6)}° ${direction}`;
  };

  const formatSpeed = (speedMs: number) => {
    const speedKmh = speedMs * 3.6;
    return `${speedKmh.toFixed(1)} km/h`;
  };

  const formatTime = (ts: string) => {
    const date = new Date(ts);
    return date.toLocaleTimeString();
  };

  const hasFix = data && data.mode >= 2;

  if (isLoading && !data) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <MapPin className="w-4 h-4 text-primary" />
            Current Location
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-6 w-3/4" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="glass-card p-0">
      <CardHeader className="pb-2 px-4 pt-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-medium flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <MapPin className="w-4 h-4 text-primary" />
            </div>
            Current Location
          </CardTitle>
          <Badge 
            variant={hasFix ? "default" : "destructive"}
            className={cn(
              "text-xs",
              hasFix && "bg-success hover:bg-success/90"
            )}
          >
            <Satellite className="w-3 h-3 mr-1" />
            {hasFix ? "Fix OK" : "No Fix"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pb-4 pt-0">
        {data ? (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Latitude</p>
                <p className="text-lg font-mono font-medium">
                  {formatCoordinate(data.lat, true)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-xs text-muted-foreground uppercase tracking-wider">Longitude</p>
                <p className="text-lg font-mono font-medium">
                  {formatCoordinate(data.lon, false)}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-2 border-t border-glass">
              <div className="flex items-center gap-2">
                <Gauge className="w-4 h-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Speed</p>
                  <p className="font-medium">{formatSpeed(data.speed_m_s)}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-muted-foreground" />
                <div>
                  <p className="text-xs text-muted-foreground">Last Update</p>
                  <p className="font-medium">{formatTime(data.ts)}</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Mountain className="w-4 h-4 text-muted-foreground" />
              <div>
                <p className="text-xs text-muted-foreground">Altitude</p>
                <p className="font-medium">
                  {data.altitude_m != null ? `${data.altitude_m.toFixed(1)} m` : "—"}
                </p>
              </div>
            </div>
          </>
        ) : (
          <p className="text-muted-foreground text-center py-4">No GPS data available</p>
        )}
      </CardContent>
    </Card>
  );
};

export default CurrentLocationCard;
