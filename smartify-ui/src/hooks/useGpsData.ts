import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch } from "@/lib/utils";

export interface GpsCurrentData {
  ts: string;
  lat: number;
  lon: number;
  speed_m_s: number;
  altitude_m?: number | null;
  satellites?: number | null;
  mode: number;
}

export interface GpsTrackPoint {
  ts: string;
  lat: number;
  lon: number;
  speed_kmh?: number | null;
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
      const response = await apiFetch("/api/gps/current");

      if (!response.ok) {
        throw new Error("Failed to fetch GPS data");
      }

      const raw = (await response.json()) as {
        ts: number | null;
        lat: number | null;
        lon: number | null;
        speed_kmh: number | null;
        altitude_m?: number | null;
        satellites?: number | null;
        ok: boolean;
      };

      const mode = raw.ok && raw.lat != null && raw.lon != null ? 2 : 0;
      const mapped: GpsCurrentData = {
        ts: raw.ts != null ? new Date(raw.ts * 1000).toISOString() : new Date().toISOString(),
        lat: raw.lat ?? 0,
        lon: raw.lon ?? 0,
        speed_m_s: raw.speed_kmh != null ? raw.speed_kmh / 3.6 : 0,
        altitude_m: raw.altitude_m ?? null,
        satellites: raw.satellites ?? null,
        mode,
      };

      setCurrentData(mapped);

      // If we have a valid fix & coordinates, compute smoothed UI coords
      if (mode >= 2 && typeof mapped.lat === "number" && typeof mapped.lon === "number") {
        const smoothed = computeSmoothed(mapped.lat, mapped.lon);
        setUiCurrentData({ ...mapped, lat: smoothed.lat, lon: smoothed.lon });
      } else {
        // No fix: don't update smoothing buffer; show raw as-is
        setUiCurrentData(mapped);
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
      const response = await apiFetch(`/api/gps/track?minutes=${trackMinutes}&limit=50000`);

      if (!response.ok) {
        throw new Error("Failed to fetch track data");
      }

      const raw = (await response.json()) as {
        rows: { ts: number; lat: number | null; lon: number | null; speed_kmh?: number | null }[];
      };

      const mapped: GpsTrackPoint[] =
        raw.rows
          ?.filter((r) => r.lat != null && r.lon != null)
          .map((r) => ({
            ts: new Date(r.ts * 1000).toISOString(),
            lat: r.lat as number,
            lon: r.lon as number,
            speed_kmh: r.speed_kmh ?? null,
          })) ?? [];

      setTrackData(mapped);
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
