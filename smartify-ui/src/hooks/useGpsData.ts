import { useState, useEffect, useCallback, useRef } from "react";

export interface GpsCurrentData {
  ts: string;
  lat: number;
  lon: number;
  speed_m_s: number;
  mode: number;
}

export interface GpsTrackPoint {
  ts: string;
  lat: number;
  lon: number;
}

type LatLon = { lat: number; lon: number };

const SMOOTH_WINDOW = 5; // last N valid points

export const useGpsData = (trackMinutes: number) => {
  const [currentData, setCurrentData] = useState<GpsCurrentData | null>(null);
  const [uiCurrentData, setUiCurrentData] = useState<GpsCurrentData | null>(null);
  const [trackData, setTrackData] = useState<GpsTrackPoint[]>([]);
  const [isLoadingCurrent, setIsLoadingCurrent] = useState(true);
  const [isLoadingTrack, setIsLoadingTrack] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const smoothBuf = useRef<LatLon[]>([]);

  const computeSmoothed = (lat: number, lon: number): LatLon => {
    smoothBuf.current.push({ lat, lon });
    if (smoothBuf.current.length > SMOOTH_WINDOW) {
      smoothBuf.current.shift();
    }
    const n = smoothBuf.current.length;
    const avgLat = smoothBuf.current.reduce((s, p) => s + p.lat, 0) / n;
    const avgLon = smoothBuf.current.reduce((s, p) => s + p.lon, 0) / n;
    return { lat: avgLat, lon: avgLon };
  };

  // Fetch current GPS data
  const fetchCurrentData = useCallback(async () => {
    try {
      const response = await fetch("/api/gps/current", {
        credentials: "include",
      });

      if (!response.ok) {
        throw new Error("Failed to fetch GPS data");
      }

      const data: GpsCurrentData = await response.json();
      setCurrentData(data);

      // If we have a valid fix & coordinates, compute smoothed UI coords
      if (data && typeof data.lat === "number" && typeof data.lon === "number" && data.mode >= 2) {
        const smoothed = computeSmoothed(data.lat, data.lon);
        setUiCurrentData({ ...data, lat: smoothed.lat, lon: smoothed.lon });
      } else {
        // No fix: don't update smoothing buffer; show raw as-is
        setUiCurrentData(data);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch GPS data");
    } finally {
      setIsLoadingCurrent(false);
    }
  }, []);

  // Fetch track data
  const fetchTrackData = useCallback(async () => {
    try {
      setIsLoadingTrack(true);
      const response = await fetch(
        `/api/gps/track?minutes=${trackMinutes}&limit=50000`,
        { credentials: "include" }
      );

      if (!response.ok) {
        throw new Error("Failed to fetch track data");
      }

      const data: GpsTrackPoint[] = await response.json();
      setTrackData(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch track data");
    } finally {
      setIsLoadingTrack(false);
    }
  }, [trackMinutes]);

  // Poll current data every 1 second
  useEffect(() => {
    fetchCurrentData();
    const interval = setInterval(fetchCurrentData, 1000);
    return () => clearInterval(interval);
  }, [fetchCurrentData]);

  // Fetch track data on mount and when minutes change, poll every 10 seconds
  useEffect(() => {
    fetchTrackData();
    const interval = setInterval(fetchTrackData, 10000);
    return () => clearInterval(interval);
  }, [fetchTrackData]);

  return {
    currentData,      // raw (debug/truth)
    uiCurrentData,    // smoothed (use for UI)
    trackData,
    isLoadingCurrent,
    isLoadingTrack,
    error,
    refreshTrack: fetchTrackData,
  };
};
