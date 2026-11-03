import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TrackPoint } from "@/api/types";

// Online OpenStreetMap tiles for now. An offline map (PMTiles extract of the
// Balkans served by the Pi) can replace this layer later.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const ACCENT = "#F0A43A";

export function TrackMap({
  points,
  position,
  cursor = null,
  height = 220,
  interactive = true,
  label,
}: {
  points: TrackPoint[];
  position: { lat: number; lon: number } | null;
  /** Index into `points` chosen with the time slider; null shows the whole route and the live position. */
  cursor?: number | null;
  height?: number | string;
  interactive?: boolean;
  label: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layers = useRef<L.LayerGroup | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    if (!element.current || map.current) return;
    map.current = L.map(element.current, {
      zoomControl: interactive,
      dragging: interactive,
      scrollWheelZoom: interactive,
      touchZoom: interactive,
      doubleClickZoom: interactive,
      keyboard: interactive,
      attributionControl: true,
    }).setView([44.2, 17.9], 7);
    L.tileLayer(TILES, { attribution: ATTRIBUTION, maxZoom: 18, className: "map-tiles" }).addTo(map.current);
    layers.current = L.layerGroup().addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, [interactive]);

  useEffect(() => {
    if (!map.current || !layers.current) return;
    layers.current.clearLayers();
    const latlngs = points.map((p) => L.latLng(p.lat, p.lon));
    const scrubbing = cursor !== null && cursor >= 0 && cursor < latlngs.length;

    if (latlngs.length > 1) {
      if (scrubbing) {
        // Whole route faint, the part driven up to the slider time solid.
        L.polyline(latlngs, { color: ACCENT, weight: 3, opacity: 0.25, dashArray: "1 7", lineCap: "round" }).addTo(
          layers.current,
        );
        const travelled = latlngs.slice(0, cursor + 1);
        if (travelled.length > 1) {
          L.polyline(travelled, { color: ACCENT, weight: 4, opacity: 0.95, lineCap: "round" }).addTo(layers.current);
        }
      } else {
        L.polyline(latlngs, { color: ACCENT, weight: 3, opacity: 0.9, dashArray: "1 7", lineCap: "round" }).addTo(
          layers.current,
        );
      }
    }

    if (position) {
      const here = L.latLng(position.lat, position.lon);
      if (!scrubbing) {
        L.circleMarker(here, { radius: 14, color: ACCENT, weight: 0, fillOpacity: 0.2 }).addTo(layers.current);
      }
      L.circleMarker(here, {
        radius: 6,
        color: "#11130E",
        weight: 2,
        fillColor: ACCENT,
        fillOpacity: scrubbing ? 0.35 : 1,
        opacity: scrubbing ? 0.5 : 1,
      }).addTo(layers.current);
    }

    if (scrubbing) {
      const van = latlngs[cursor];
      L.circleMarker(van, { radius: 16, color: ACCENT, weight: 0, fillOpacity: 0.25 }).addTo(layers.current);
      L.circleMarker(van, { radius: 8, color: "#11130E", weight: 3, fillColor: "#FFFFFF", fillOpacity: 1 }).addTo(
        layers.current,
      );
      // Keep the van in view while sliding, without changing the zoom.
      if (!map.current.getBounds().pad(-0.1).contains(van)) map.current.panTo(van, { animate: true });
    }

    if (!fitted.current) {
      if (latlngs.length > 1) {
        map.current.fitBounds(L.latLngBounds(latlngs).pad(0.2), { maxZoom: 14 });
        fitted.current = true;
      } else if (position) {
        map.current.setView([position.lat, position.lon], 13);
        fitted.current = true;
      }
    }
  }, [points, position, cursor]);

  return <div ref={element} className="map" style={{ height }} role="img" aria-label={label} />;
}
