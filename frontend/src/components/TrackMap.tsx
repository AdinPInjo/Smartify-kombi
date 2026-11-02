import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TrackPoint } from "@/api/types";

// Online OpenStreetMap tiles for now. An offline map (PMTiles extract of the
// Balkans served by the Pi) can replace this layer later.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export function TrackMap({
  points,
  position,
  height = 220,
  interactive = true,
  label,
}: {
  points: TrackPoint[];
  position: { lat: number; lon: number } | null;
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
    if (latlngs.length > 1) {
      L.polyline(latlngs, { color: "#F0A43A", weight: 3, opacity: 0.9, dashArray: "1 7", lineCap: "round" }).addTo(
        layers.current,
      );
    }
    if (position) {
      const here = L.latLng(position.lat, position.lon);
      L.circleMarker(here, { radius: 14, color: "#F0A43A", weight: 0, fillOpacity: 0.2 }).addTo(layers.current);
      L.circleMarker(here, { radius: 6, color: "#11130E", weight: 2, fillColor: "#F0A43A", fillOpacity: 1 }).addTo(
        layers.current,
      );
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
  }, [points, position]);

  return <div ref={element} className="map" style={{ height }} role="img" aria-label={label} />;
}
