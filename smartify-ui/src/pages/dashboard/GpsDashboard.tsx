import { useMemo, useState } from "react";
import { useGpsData } from "@/hooks/useGpsData";
import CurrentLocationCard from "@/components/gps/CurrentLocationCard";
import TimeWindowControl from "@/components/gps/TimeWindowControl";
import GpsMap from "@/components/gps/GpsMap";
import RecentPointsTable from "@/components/gps/RecentPointsTable";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";

const GpsDashboard = () => {
  const [trackMinutes, setTrackMinutes] = useState(60);
  const { currentData, uiCurrentData, trackData, isLoadingCurrent, isLoadingTrack, error } =
    useGpsData(trackMinutes);

  // Use smoothed for UI when available, fallback to raw
  const displayData = uiCurrentData ?? currentData;

  // This changes ONLY when the user changes time window => triggers fitBounds once
  const fitKey = useMemo(() => `minutes:${trackMinutes}`, [trackMinutes]);

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left column */}
        <div className="lg:col-span-4 space-y-6">
          <CurrentLocationCard data={displayData} isLoading={isLoadingCurrent} />

          <TimeWindowControl
            minutes={trackMinutes}
            onMinutesChange={setTrackMinutes}
          />

          <RecentPointsTable points={trackData} isLoading={isLoadingTrack} />
        </div>

        {/* Right column - Map */}
        <div className="lg:col-span-8">
          <GpsMap
            currentData={displayData}
            trackData={trackData}
            isLoading={isLoadingTrack}
            fitKey={fitKey}
          />
        </div>
      </div>
    </div>
  );
};

export default GpsDashboard;
