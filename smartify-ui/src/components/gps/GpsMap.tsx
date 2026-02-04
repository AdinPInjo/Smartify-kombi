import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

import { cn } from "@/lib/utils";
import type { GpsCurrentData, GpsTrackPoint } from "@/hooks/useGpsData";

type Props = {
  currentData: GpsCurrentData | null;
  trackData: GpsTrackPoint[];
  isLoading: boolean;
  fitKey: string;
  className?: string;
};

function isValidLatLon(lat?: number, lon?: number) {
  return typeof lat === "number" && typeof lon === "number" && !Number.isNaN(lat) && !Number.isNaN(lon);
}

const GpsMap = ({ currentData, trackData, isLoading, fitKey, className }: Props) => {
  const mapDivRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const circleRef = useRef<L.CircleMarker | null>(null);
  const polyRef = useRef<L.Polyline | null>(null);

  // Fit control refs:
  const lastFitKeyRef = useRef<string>("");
  const didFitForKeyRef = useRef<boolean>(false);

  const trackLatLngs = useMemo(() => {
    return trackData
      .filter((p) => isValidLatLon(p.lat, p.lon))
      .map((p) => L.latLng(p.lat, p.lon));
  }, [trackData]);

  const currentPos = useMemo(() => {
    if (currentData && currentData.mode >= 2 && isValidLatLon(currentData.lat, currentData.lon)) {
      return L.latLng(currentData.lat, currentData.lon);
    }
    return null;
  }, [currentData]);

  // Marker that does NOT depend on external PNG assets
  const dotIcon = useMemo(
    () =>
      L.divIcon({
        className: "",
        html: `<div class="gps-pulse-wrap">
          <div class="gps-pulse-ring"></div>
          <div class="gps-pulse-core"></div>
        </div>`,
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }),
    []
  );

  // Create map once
  useEffect(() => {
    if (!mapDivRef.current) return;
    if (mapRef.current) return;

    const fallback = L.latLng(43.8563, 18.4131);

    const map = L.map(mapDivRef.current, {
      center: fallback,
      zoom: 12,
      zoomControl: true,
    });

    const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    });

    // Add error logging for tile loading failures
    tileLayer.on("tileerror", (error, tile) => {
      console.error("[GpsMap] Tile load error:", {
        error,
        url: tile.src,
        tile: tile,
      });
    });

    tileLayer.addTo(map);

    polyRef.current = L.polyline([], {}).addTo(map);
    markerRef.current = L.marker(currentPos ?? fallback, { icon: dotIcon }).addTo(map);
    circleRef.current = L.circleMarker(currentPos ?? fallback, {
      radius: 6,
      color: "#22c55e",
      fillColor: "#22c55e",
      fillOpacity: 0.9,
      weight: 2,
    }).addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
      circleRef.current = null;
      polyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update polyline points on every track refresh (no zoom change)
  useEffect(() => {
    if (!polyRef.current) return;
    polyRef.current.setLatLngs(trackLatLngs);
  }, [trackLatLngs]);

  // Update marker position on every current refresh (no zoom change)
  useEffect(() => {
    if (!markerRef.current) return;
    if (!currentPos) return;
    markerRef.current.setLatLng(currentPos);
    if (circleRef.current) {
      circleRef.current.setLatLng(currentPos);
    }
  }, [currentPos]);

  // Fit logic:
  // - When fitKey changes (slider/preset), allow one fit again
  // - Also: do an initial fit once data actually arrives
  useEffect(() => {
    if (fitKey !== lastFitKeyRef.current) {
      lastFitKeyRef.current = fitKey;
      didFitForKeyRef.current = false;
    }

    const map = mapRef.current;
    if (!map) return;

    if (didFitForKeyRef.current) return;

    if (trackLatLngs.length >= 2) {
      const bounds = L.latLngBounds(trackLatLngs);
      map.fitBounds(bounds, { padding: [20, 20] });
      didFitForKeyRef.current = true;
      return;
    }

    if (currentPos) {
      map.setView(currentPos, 16);
      didFitForKeyRef.current = true;
    }
  }, [fitKey, trackLatLngs, currentPos]);

  return (
    <div className={cn("relative h-[70vh] w-full overflow-hidden rounded-xl border border-glass bg-background", className)}>
      <div ref={mapDivRef} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-0 opacity-20">
        <svg className="w-full h-full" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="map-grid" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="currentColor" strokeWidth="0.5" className="text-primary" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#map-grid)" />
        </svg>
      </div>
      {isLoading && (
        <div className="pointer-events-none absolute left-0 top-0 flex h-full w-full items-center justify-center">
          <div className="rounded-md border bg-background/80 px-3 py-2 text-sm">
            Loading map…
          </div>
        </div>
      )}
    </div>
  );
};

export default GpsMap;
