import { useEffect, useMemo, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { MapPin, Home, Warehouse, Thermometer, Battery, Power, Droplets, Activity, Gauge, Plus, Settings2, ListChecks, Sun, CloudRain, CloudSun, CloudSnow, CloudLightning } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/utils";
import { getOverviewLayout, OverviewModuleId } from "@/lib/overviewLayout";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";
import gpsSea from "@/assets/gps/sea.jpg";
import gpsHills from "@/assets/gps/hills.jpg";
import gpsMountain from "@/assets/gps/mountain.jpg";

type TempPayload = {
  ts: number | null;
  kombi: { temp_c: number | null; hum_pct: number | null };
  garaza: { temp_c: number | null; hum_pct: number | null };
};

type GpsPayload = {
  ts: number | null;
  lat: number | null;
  lon: number | null;
  speed_kmh: number | null;
  course: number | null;
  altitude_m: number | null;
  satellites?: number | null;
  ok: boolean;
  error: string | null;
};

type TrackPoint = { ts: string; lat: number; lon: number; speed_m_s?: number | null; mode?: number | null };
type TrackPayload = { hours: number; count: number; points: TrackPoint[] };
type WeatherForecastPayload = {
  ok: boolean;
  current?: { temp_c: number | null; weather_code: number | null; wind_kmh: number | null };
  daily: Array<{ date: string; temp_max: number | null; temp_min: number | null; weather_code: number | null }>;
};

function formatTemp(t: number | null) {
  return t == null ? "—" : `${t.toFixed(1)}°C`;
}
function formatHum(h: number | null) {
  return h == null ? "" : `${h.toFixed(0)}%`;
}
function tempClass(t: number | null) {
  if (t == null) return "ring-1 ring-white/10";
  if (t < 8) return "ring-1 ring-sky-400/40";
  if (t < 16) return "ring-1 ring-emerald-400/40";
  if (t < 24) return "ring-1 ring-amber-400/40";
  return "ring-1 ring-red-400/40";
}

function tempStyle(t: number | null) {
  if (t == null) return { card: "bg-secondary/30 border-glass", text: "text-muted-foreground", Icon: Thermometer };
  if (t < 8) return { card: "bg-sky-500/10 border-sky-400/30", text: "text-sky-200", Icon: CloudSnow };
  if (t < 16) return { card: "bg-emerald-500/10 border-emerald-400/30", text: "text-emerald-200", Icon: CloudSun };
  if (t < 24) return { card: "bg-amber-500/10 border-amber-400/30", text: "text-amber-200", Icon: Sun };
  return { card: "bg-red-500/10 border-red-400/30", text: "text-red-200", Icon: Sun };
}

function tempLabel(t: number | null) {
  if (t == null) return "Unknown";
  if (t < 8) return "Cold";
  if (t < 16) return "Cool";
  if (t < 24) return "Comfort";
  return "Hot";
}

function formatTimeAgo(timestampSec: number | null) {
  if (!timestampSec) return "Unknown";
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - timestampSec);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function weatherTheme(code: number | null | undefined) {
  if (code == null) return { theme: "weather-cloud", icon: CloudSun, label: "Mixed" };
  if (code === 0) return { theme: "weather-sun", icon: Sun, label: "Clear" };
  if (code >= 1 && code <= 3) return { theme: "weather-cloud", icon: CloudSun, label: "Partly Cloudy" };
  if (code >= 45 && code <= 48) return { theme: "weather-cloud", icon: CloudSun, label: "Fog" };
  if (code >= 51 && code <= 67) return { theme: "weather-rain", icon: CloudRain, label: "Rain" };
  if (code >= 71 && code <= 77) return { theme: "weather-snow", icon: CloudSnow, label: "Snow" };
  if (code >= 80 && code <= 82) return { theme: "weather-rain", icon: CloudRain, label: "Showers" };
  if (code >= 95) return { theme: "weather-storm", icon: CloudLightning, label: "Storm" };
  return { theme: "weather-cloud", icon: CloudSun, label: "Mixed" };
}

function ForecastChip({ day, max, min, code }: { day: string; max: number | null; min: number | null; code: number | null }) {
  const { icon: Icon, label } = weatherTheme(code);
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl bg-secondary/30 border border-glass px-3 py-2 text-center">
      <div className="text-xs text-muted-foreground">{day}</div>
      <Icon className="h-5 w-5 text-primary" />
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold text-foreground">
        {max != null ? max.toFixed(0) : "—"}° / {min != null ? min.toFixed(0) : "—"}°
      </div>
    </div>
  );
}


function GpsMiniMap({ lat, lon }: { lat: number | null; lon: number | null }) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    if (mapRef.current) return;

    const map = L.map(elRef.current, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false as any,
      touchZoom: false,
    }).setView([43.8563, 18.4131], 10);

    const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    });

    tileLayer.on("tileerror", (error, tile) => {
      console.error("[GpsMiniMap] Tile load error:", {
        error,
        url: tile.src,
        tile: tile,
      });
    });

    tileLayer.addTo(map);

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (lat == null || lon == null) return;

    setTimeout(() => {
    map.setView([lat, lon], 14);
      map.invalidateSize();

    if (!markerRef.current) {
        markerRef.current = L.circleMarker([lat, lon], { radius: 6, color: "#3b82f6", fillColor: "#3b82f6", fillOpacity: 0.8 });
      markerRef.current.addTo(map);
    } else {
      markerRef.current.setLatLng([lat, lon]);
    }
    }, 100);
  }, [lat, lon]);

  return <div ref={elRef} className="h-32 w-full rounded-xl overflow-hidden border border-glass bg-secondary/30" />;
}

function GpsTrackMap({ data, currentLat, currentLon }: { data: TrackPayload | null; currentLat: number | null; currentLon: number | null }) {
  const elRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const markerRef = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    if (!elRef.current) return;
    if (mapRef.current) return;

    // Initialize map with current location if available, otherwise default
    const initLat = currentLat ?? 43.8563;
    const initLon = currentLon ?? 18.4131;

    const map = L.map(elRef.current, { zoomControl: true, attributionControl: true }).setView([initLat, initLon], currentLat && currentLon ? 12 : 9);

    const tileLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    });

    tileLayer.on("tileerror", (error, tile) => {
      console.error("[GpsTrackMap] Tile load error:", {
        error,
        url: tile.src,
        tile: tile,
      });
    });

    tileLayer.addTo(map);

    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);

    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      markerRef.current = null;
    };
  }, []);

  // Update map when current location changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (currentLat != null && currentLon != null) {
      // Validate coordinates are reasonable
      if (currentLat >= -90 && currentLat <= 90 && currentLon >= -180 && currentLon <= 180) {
        setTimeout(() => {
          map.setView([currentLat, currentLon], 12);
          map.invalidateSize();

          // Update or create current position marker
          if (!markerRef.current) {
            markerRef.current = L.circleMarker([currentLat, currentLon], { 
              radius: 8, 
              color: "#10b981", 
              fillColor: "#10b981", 
              fillOpacity: 0.9,
              weight: 2
            });
            markerRef.current.addTo(map);
          } else {
            markerRef.current.setLatLng([currentLat, currentLon]);
          }
        }, 100);
      }
    }
  }, [currentLat, currentLon]);

  // Update track polyline
  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;

    // Clear only the track (polyline), keep the current position marker
    const layersToRemove: L.Layer[] = [];
    layer.eachLayer((l) => {
      if (l instanceof L.Polyline || (l instanceof L.CircleMarker && l !== markerRef.current)) {
        layersToRemove.push(l);
      }
    });
    layersToRemove.forEach((l) => layer.removeLayer(l));

    const pts = data?.points ?? [];
    if (pts.length === 0) return;

    const latlngs: L.LatLngExpression[] = pts.map((p) => {
      // Validate coordinates
      if (p.lat >= -90 && p.lat <= 90 && p.lon >= -180 && p.lon <= 180) {
        return [p.lat, p.lon];
      }
      return null;
    }).filter((p): p is L.LatLngExpression => p !== null);

    if (latlngs.length === 0) return;

    const poly = L.polyline(latlngs, { weight: 3, color: "#3b82f6", opacity: 0.7 });
    poly.addTo(layer);

    // Add end marker (if different from current position)
    const last = pts[pts.length - 1];
    if (last && (last.lat !== currentLat || last.lon !== currentLon)) {
      if (last.lat >= -90 && last.lat <= 90 && last.lon >= -180 && last.lon <= 180) {
        L.circleMarker([last.lat, last.lon], { 
          radius: 6, 
          color: "#3b82f6", 
          fillColor: "#3b82f6", 
          fillOpacity: 0.6 
        }).addTo(layer);
      }
    }

    // Fit bounds to show both track and current position
    const bounds = poly.getBounds();
    if (currentLat != null && currentLon != null) {
      bounds.extend([currentLat, currentLon]);
    }
    map.fitBounds(bounds, { padding: [20, 20] });
  }, [data, currentLat, currentLon]);

  return <div ref={elRef} className="h-[230px] w-full rounded-xl overflow-hidden border border-glass bg-secondary/30" />;
}

function HeaderRelayCard() {
  const queryClient = useQueryClient();

  // Fetch heater relay from new API
  const { data: relaysResponse, isLoading, error } = useQuery({
    queryKey: ["relays", "heater"],
    queryFn: async () => {
      const r = await apiFetch("/api/relays", { cache: "no-store" });
      if (!r.ok) throw new Error(`Relays API returned ${r.status}`);
      const data = await r.json();
      // Find heater relay - ensure relays is an array
      const relays = Array.isArray(data.relays) ? data.relays : [];
      const heater = relays.find((relay: any) => relay.name === "heater");
      if (!heater) throw new Error("Heater relay not found");
      return heater as {
        id: string;
        name: string;
        pin: number;
        state: "on" | "off";
        mode: "auto" | "manual";
        manual_until: number | null;
        updated_at: number | null;
        is_enabled: boolean;
        pending?: boolean;
        pending_reason?: string;
        pending_message?: string;
        cooldown_remaining?: number | null;
        sensor_age_seconds?: number | null;
        sensor_sample_count?: number | null;
        sensor_is_ready?: boolean | null;
        sensor_is_stale?: boolean | null;
        source?: string;
      };
    },
    retry: 1,
    refetchInterval: (query) => {
      // Poll more frequently (1.5s) when relay is pending, otherwise 5s
      const heater = query.state.data;
      const hasPending = heater?.pending === true;
      return hasPending ? 1500 : 5000;
    },
  });

  // Mutation to toggle relay state (manual mode)
  const toggleMutation = useMutation({
    mutationFn: async (newState: "on" | "off") => {
      if (!relaysResponse) throw new Error("Relay not loaded");
      
      // Send logical state (user intent) - backend will handle hardware inversion
      const r = await apiFetch(`/api/relays/${relaysResponse.id}/state`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          state: newState,  // Logical state (what user wants)
          mode: "manual",
        }),
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to set relay: ${r.status}`);
      }
      const result = await r.json();
      // Refetch relays to get updated state
      await queryClient.invalidateQueries({ queryKey: ["relays"] });
      await queryClient.invalidateQueries({ queryKey: ["relays", "heater"] });
      return result;
    },
    onError: (error) => {
      console.error("[HeaderRelayCard] Failed to toggle relay:", error);
      toast.error("Failed to toggle relay", {
        description: error instanceof Error ? error.message : "Unknown error occurred",
      });
      queryClient.invalidateQueries({ queryKey: ["relays"] });
      queryClient.invalidateQueries({ queryKey: ["relays", "heater"] });
    },
  });

  // Mutation to return to auto mode
  const setAutoMutation = useMutation({
    mutationFn: async () => {
      if (!relaysResponse) throw new Error("Relay not loaded");
      const r = await apiFetch(`/api/relays/${relaysResponse.id}/auto`, {
        method: "POST",
        cache: "no-store",
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ error: "unknown" }));
        throw new Error(err.message || `Failed to set auto mode: ${r.status}`);
      }
      await queryClient.invalidateQueries({ queryKey: ["relays"] });
      await queryClient.invalidateQueries({ queryKey: ["relays", "heater"] });
      return await r.json();
    },
    onError: (error) => {
      toast.error("Failed to set auto mode", {
        description: error instanceof Error ? error.message : "Unknown error occurred",
      });
    },
  });

  // Use pending state from API response (backend calculates cooldown/reconciling/startup)
  const isPending = relaysResponse?.pending === true;
  const pendingMessage = relaysResponse?.pending_message || "Relay is in pending state";
  const cooldownRemaining = relaysResponse?.cooldown_remaining ?? null;
  const sensorSampleCount = relaysResponse?.sensor_sample_count ?? null;

  // Backend stores logical state (what user wants, not hardware command)
  const isOn = relaysResponse?.state === "on";  // Logical state: "on" means relay should be ON
  const isManual = relaysResponse?.mode === "manual";
  const manualUntil = relaysResponse?.manual_until;
  // Disable controls when pending (cooldown/reconciling/startup) or during mutations
  const isDisabled = isLoading || toggleMutation.isPending || setAutoMutation.isPending || !!error || isPending;
  const isUpdating = toggleMutation.isPending || setAutoMutation.isPending;

  const handleToggle = (checked: boolean) => {
    // Never allow toggle when pending - backend will reject anyway
    if (isPending) {
      return;
    }
    // Send logical state (user intent) - backend handles hardware inversion
    const newState: "on" | "off" = checked ? "on" : "off";
    toggleMutation.mutate(newState);
  };

  const handleReturnToAuto = () => {
    setAutoMutation.mutate();
  };

  return (
    <Card className="glass-card p-0 h-full card-compact relay-card">
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <Power className="h-4 w-4 text-primary" />
          </div>
          Header Relay
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pb-4 pt-0">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-foreground">Main Power</p>
            {error ? (
              <p className="text-sm text-destructive">Offline</p>
            ) : isUpdating ? (
              <p className="text-sm text-muted-foreground">Updating...</p>
            ) : (
              <p className="text-sm text-muted-foreground">
                {isOn ? "Currently active" : "Currently off"}
              </p>
            )}
            {manualUntil && manualUntil > Date.now() / 1000 && (
              <p className="text-xs text-muted-foreground">
                Manual until {new Date(manualUntil * 1000).toLocaleTimeString()}
              </p>
            )}
          </div>
          <div className="flex items-center gap-3">
            {isUpdating && (
              <div className="h-4 w-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            )}
            {isPending && !isUpdating && (
              <div className="h-4 w-4 border-2 border-muted border-t-transparent rounded-full animate-spin opacity-50" />
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Switch
                      checked={isOn}
                      onCheckedChange={handleToggle}
                      disabled={isDisabled}
                      className="data-[state=checked]:bg-primary data-[state=unchecked]:bg-secondary"
                    />
                  </div>
                </TooltipTrigger>
                {isPending && (
                  <TooltipContent>
                    <p className="text-sm font-medium">
                      {pendingMessage}
                      {cooldownRemaining !== null && cooldownRemaining > 0 && (
                        <span className="ml-1 text-primary">({cooldownRemaining}s)</span>
                      )}
                    </p>
                    {sensorSampleCount !== null && relaysResponse?.sensor_sample_count !== undefined && (
                      <p className="text-xs text-muted-foreground mt-1">
                        Progress: {sensorSampleCount}/6 samples collected
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground mt-1">
                      Manual control is disabled during this period.
                    </p>
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
        {isManual && (
          <Button
            size="sm"
            variant="outline"
            className="w-full"
            onClick={handleReturnToAuto}
            disabled={isDisabled || isPending}
          >
            Return to Auto
          </Button>
        )}
        {error && (
          <div className="text-xs text-destructive bg-destructive/10 border border-destructive/20 rounded px-2 py-1">
            Failed to connect to relay
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type WaterLevelPayload = {
  ok: boolean;
  level_percent: number | null;
  avg_voltage: number | null; // Backward compatibility (signal voltage)
  signal_voltage?: number | null;
  supply_div_voltage?: number | null;
  supply_voltage_est?: number | null;
  ratio?: number | null;
  status: "ok" | "stale" | "error" | "calibrating" | "unknown";
  age_seconds: number;
  message: string;
  calibration_full_voltage?: number | null;
  calibration_empty_voltage?: number | null;
  use_supply_normalization?: boolean;
};

function WaterLevelCard() {
  const { data: waterData, isLoading } = useQuery<WaterLevelPayload>({
    queryKey: ["water-level-live"],
    queryFn: async () => {
      const r = await apiFetch("/api/water/level/live", { cache: "no-store" });
      if (!r.ok) throw new Error(`Water level API returned ${r.status}`);
      const data = await r.json();
      // Transform live response to match expected payload format
      return {
        ok: data.ok,
        level_percent: data.level_percent ?? null,
        status: data.status || (data.ok ? "ok" : "error"),
        message: data.message || (data.ok ? "Reading stable" : "Error"),
        age_seconds: 0, // Live data is always current
      };
    },
    refetchInterval: 4000, // Poll every 4 seconds for fast updates
    placeholderData: (previousData) => previousData, // Keep previous data during refetch
    retry: 2,
  });

  const levelPercent = waterData?.level_percent ?? null;

  const waterStyle =
    levelPercent == null
      ? { card: "bg-secondary/30 border-glass", text: "text-muted-foreground", bar: "bg-secondary", label: "Unknown" }
      : levelPercent > 60
      ? { card: "bg-emerald-500/10 border-emerald-400/30", text: "text-emerald-200", bar: "bg-success", label: "Full" }
      : levelPercent > 30
      ? { card: "bg-amber-500/10 border-amber-400/30", text: "text-amber-200", bar: "bg-warning", label: "Medium" }
      : { card: "bg-red-500/10 border-red-400/30", text: "text-red-200", bar: "bg-destructive", label: "Low" };

  return (
    <Card className={`glass-card p-0 h-full card-compact water-card ${waterStyle.card}`}>
      <CardHeader className="pb-2 px-4 pt-4">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <Droplets className="h-4 w-4 text-primary" />
          </div>
          Water Level
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 px-4 pb-4 pt-0">
        <div className="flex items-end justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Status</p>
            <p className={`text-sm font-semibold ${waterStyle.text}`}>{waterStyle.label}</p>
          </div>
          <div className="text-right">
            <span className={`text-3xl font-bold ${waterStyle.text}`}>
              {levelPercent !== null ? `${levelPercent}%` : "—"}
            </span>
          </div>
        </div>
        <div className="h-3 bg-secondary/50 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${waterStyle.bar}`}
            style={{ width: `${levelPercent ?? 0}%` }}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          {waterData?.message ?? "—"}
        </p>
      </CardContent>
    </Card>
  );
}

function RelayRulesWidget() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Fetch heater relay
  const { data: relaysResponse } = useQuery({
    queryKey: ["relays", "heater"],
    queryFn: async () => {
      const r = await apiFetch("/api/relays", { cache: "no-store" });
      if (!r.ok) throw new Error(`Relays API returned ${r.status}`);
      const data = await r.json();
      // Ensure we have a valid relays array
      if (!data || typeof data !== "object") {
        throw new Error("Invalid API response format");
      }
      const relays = Array.isArray(data.relays) ? data.relays : [];
      return relays.find((relay: any) => relay.name === "heater") || null;
    },
    retry: 1,
  });

  const heaterId = relaysResponse?.id;

  // Fetch rules for heater relay
  const { data: rulesResponse, isLoading } = useQuery({
    queryKey: ["relay-rules", heaterId],
    queryFn: async () => {
      if (!heaterId) return { rules: [] };
      const r = await apiFetch(`/api/relays/${heaterId}/rules`, { cache: "no-store" });
      if (!r.ok) throw new Error(`Rules API returned ${r.status}`);
      return await r.json();
    },
    enabled: !!heaterId,
    retry: 1,
  });

  const rules = rulesResponse?.rules || [];
  const enabledRules = rules.filter((r: any) => r.is_enabled);
  const lastFiredRule = rules
    .filter((r: any) => r.last_triggered_at)
    .sort((a: any, b: any) => (b.last_triggered_at || 0) - (a.last_triggered_at || 0))[0];

  const formatCondition = (cond: any): string => {
    if (!cond) return "always";
    if (cond.op === "and" || cond.op === "or") {
      const joiner = cond.op.toUpperCase();
      const parts = (cond.conditions || []).map((c: any) => formatCondition(c));
      return parts.length ? `(${parts.join(` ${joiner} `)})` : "always";
    }
    if (cond.op === "not") {
      return `NOT (${formatCondition(cond.condition)})`;
    }
    if (cond.type === "temperature") {
      const sensor = cond.sensor || "sensor";
      const cmp = cond.cmp || cond.operator || "?";
      return `${sensor} ${cmp} ${cond.value}°C`;
    }
    if (cond.type === "temperature_between") {
      const sensor = cond.sensor || "sensor";
      const minSym = cond.min_inclusive === false ? ">" : "≥";
      const maxSym = cond.max_inclusive === true ? "≤" : "<";
      return `${sensor} ${minSym} ${cond.min}°C AND ${sensor} ${maxSym} ${cond.max}°C`;
    }
    if (cond.type === "humidity") {
      const sensor = cond.sensor || "sensor";
      const cmp = cond.cmp || cond.operator || "?";
      return `${sensor} ${cmp} ${cond.value}%`;
    }
    if (cond.type === "humidity_between") {
      const sensor = cond.sensor || "sensor";
      const minSym = cond.min_inclusive === false ? ">" : "≥";
      const maxSym = cond.max_inclusive === true ? "≤" : "<";
      return `${sensor} ${minSym} ${cond.min}% AND ${sensor} ${maxSym} ${cond.max}%`;
    }
    return "condition";
  };

  const formatAction = (action: any): string => {
    if (!action) return "set";
    if (typeof action === "string") {
      return action === "turn_on" ? "Set ON" : action === "turn_off" ? "Set OFF" : action;
    }
    if (action.type === "set_state") {
      return `Set ${action.state?.toUpperCase()}`;
    }
    if (action.type === "temperature_band") {
      const minSym = action.min_inclusive === false ? ">" : "≥";
      const maxSym = action.max_inclusive === true ? "≤" : "<";
      return `${action.sensor || "sensor"} ${minSym} ${action.min}°C AND ${action.sensor || "sensor"} ${maxSym} ${action.max}°C → ${action.on_state?.toUpperCase() || "ON"}`;
    }
    return "action";
  };

  const formatRuleDescription = (rule: any) => {
    return `${formatCondition(rule.condition)} → ${formatAction(rule.action)}`;
  };

  const formatTimeAgo = (timestamp: number | null) => {
    if (!timestamp) return "Never";
    const seconds = Math.floor(Date.now() / 1000) - timestamp;
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  return (
    <Card className="glass-card p-0 h-full card-compact rules-card flex flex-col">
      <CardHeader className="pb-3 px-4 pt-4">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-primary/20 border border-glass">
            <ListChecks className="h-4 w-4 text-primary" />
          </div>
          <div>
            <CardTitle className="text-lg font-semibold text-foreground">Active Rules</CardTitle>
            <p className="text-sm text-muted-foreground mt-1">
              {enabledRules.length} active rule{enabledRules.length !== 1 ? "s" : ""}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col px-4 pb-4 pt-0">
        <div className="mt-auto space-y-3">
          {isLoading ? (
            <div className="text-sm text-muted-foreground text-center py-4">Loading rules...</div>
          ) : rules.length === 0 ? (
            <div className="rounded-lg border-2 border-dashed border-glass p-6 text-center">
              <Settings2 className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">No rules configured</p>
              <p className="text-xs text-muted-foreground mt-1">Create rules in Relay Settings</p>
            </div>
          ) : (
            rules.slice(0, 3).map((rule: any) => (
              <div
                key={rule.id}
                className="flex items-center justify-between p-3 rounded-xl bg-secondary/30 border border-glass"
              >
                <div className="flex items-center gap-3">
                  <Thermometer className="w-4 h-4 text-muted-foreground" />
                  <div>
                    <p className="font-medium text-sm text-foreground">{rule.name}</p>
                    <p className="text-xs text-muted-foreground">{formatRuleDescription(rule)}</p>
                  </div>
                </div>
                <span className={rule.is_enabled ? "status-dot-online" : "status-dot-offline"} />
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function OverviewDashboard() {
  const [track, setTrack] = useState<TrackPayload | null>(null);
  const [layout, setLayout] = useState(getOverviewLayout());
  const [lastAddress, setLastAddress] = useState<string | null>(null);

  useEffect(() => {
    const handler = () => setLayout(getOverviewLayout());
    window.addEventListener("overview-layout-change", handler);
    return () => window.removeEventListener("overview-layout-change", handler);
  }, []);

  // GPS current data with React Query (polls every 60s, keeps previous data)
  const { data: gpsData } = useQuery({
    queryKey: ["gps", "current"],
    queryFn: async () => {
      const r = await apiFetch("/api/gps/current", { cache: "no-store" });
      if (!r.ok) throw new Error(`GPS API returned ${r.status}`);
      return (await r.json()) as GpsPayload;
    },
    refetchInterval: 60000, // Poll every 60 seconds (1 minute)
    placeholderData: (previousData) => previousData, // keepPreviousData equivalent
    retry: 1,
  });

  const gps = gpsData ?? null;

  // Temperature data with React Query (polls every 2s, keeps previous data)
  const { data: tempData } = useQuery({
    queryKey: ["temperature", "latest"],
    queryFn: async () => {
      const r = await apiFetch("/api/temperature/latest", { cache: "no-store" });
      if (!r.ok) throw new Error(`Temperature API returned ${r.status}`);
      return (await r.json()) as {
        ts: number;
        sensors: Array<{
          sensor_index: number;
          pin: number;
          temperature_c: number | null;
          humidity: number | null;
          ok: boolean;
          error: string | null;
        }>;
      };
    },
    refetchInterval: 2000, // Poll every 2 seconds
    placeholderData: (previousData) => previousData, // keepPreviousData equivalent
    retry: 1,
  });

  // Transform temperature data
  const temps = useMemo<TempPayload | null>(() => {
    if (!tempData) return null;

    const raw = tempData;
    if (!raw.sensors || raw.sensors.length === 0) {
      return {
        ts: raw.ts ?? null,
        kombi: { temp_c: null, hum_pct: null },
        garaza: { temp_c: null, hum_pct: null },
      };
    }

    const s0 = raw.sensors.find((s) => s.sensor_index === 0) ?? raw.sensors[0] ?? null;
    const s1 = raw.sensors.find((s) => s.sensor_index === 1) ?? (raw.sensors.length > 1 ? raw.sensors[1] : null) ?? null;

    return {
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
  }, [tempData]);

  const { data: weatherCurrent } = useQuery({
    queryKey: ["weather", "current"],
    queryFn: async () => {
      const r = await apiFetch("/api/weather/current", { cache: "no-store" });
      if (!r.ok) throw new Error(`Weather API returned ${r.status}`);
      return (await r.json()) as { ok: boolean; temp_c: number | null };
    },
    refetchInterval: 60000,
    retry: 1,
  });

  const { data: weatherForecast } = useQuery({
    queryKey: ["weather", "forecast"],
    queryFn: async () => {
      const r = await apiFetch("/api/weather/forecast", { cache: "no-store" });
      if (!r.ok) throw new Error(`Weather forecast API returned ${r.status}`);
      return (await r.json()) as WeatherForecastPayload;
    },
    refetchInterval: 600000,
    retry: 1,
  });



  // GPS track (24h)
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch("/api/gps/track?hours=24", { cache: "no-store" });
        if (!r.ok) return;

        const raw = (await r.json()) as {
          since: number;
          now: number;
          rows: Array<{ ts: number; lat: number | null; lon: number | null; speed_kmh: number | null; course: number | null; altitude_m: number | null }>;
        };

        // Transform backend format to component format
        const transformed: TrackPayload = {
          hours: 24,
          count: raw.rows.length,
          points: raw.rows
            .filter((p) => p.lat != null && p.lon != null)
            .map((p) => ({
              ts: new Date(p.ts * 1000).toISOString(),
              lat: p.lat!,
              lon: p.lon!,
              speed_m_s: p.speed_kmh != null ? p.speed_kmh / 3.6 : null,
            })),
        };

        if (alive) setTrack(transformed);
      } catch {}
    };
    tick();
    const id = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const gpsHasFix = gps?.lat != null && gps?.lon != null;
  const speedKmh = useMemo(() => gps?.speed_kmh ?? null, [gps?.speed_kmh]);

  const kombiT = temps?.kombi?.temp_c ?? null;
  const outsideT = weatherCurrent?.ok ? weatherCurrent.temp_c ?? null : null;
  const forecastDays = (weatherForecast?.daily || []).slice(1, 5);
  const currentForecast = weatherForecast?.current ?? null;
  const currentWeatherCode = currentForecast?.weather_code ?? null;
  const weatherMeta = weatherTheme(currentWeatherCode);
  const WeatherIcon = weatherMeta.icon;
  const currentOutsideTemp = currentForecast?.temp_c ?? outsideT;
  const altitudeM = gps?.altitude_m ?? null;
  const terrainClass =
    altitudeM == null
      ? "gps-terrain-mid"
      : altitudeM < 200
      ? "gps-terrain-low"
      : altitudeM >= 1000
      ? "gps-terrain-high"
      : "gps-terrain-mid";
  const gpsBg =
    altitudeM == null
      ? gpsHills
      : altitudeM < 200
      ? gpsSea
      : altitudeM >= 1000
      ? gpsMountain
      : gpsHills;

  const gpsStatus = gps?.ok === false ? "Disconnected" : gpsHasFix ? "Fix" : "No fix";

  // Reverse geocoding for address
  const { data: address } = useQuery({
    queryKey: ["address", gps?.lat, gps?.lon],
    queryFn: async () => {
      if (!gpsHasFix || !gps?.lat || !gps?.lon) return null;
      try {
        const response = await fetch(
          `https://nominatim.openstreetmap.org/reverse?format=json&lat=${gps.lat}&lon=${gps.lon}&zoom=16&addressdetails=1`,
          {
            headers: {
              "User-Agent": "Smartify-Dashboard/1.0",
            },
          }
        );
        if (!response.ok) return null;
        const data = await response.json();
        const addr = data.address;
        if (!addr) return null;
        
        const parts = [];
        if (addr.road) parts.push(addr.road);
        if (addr.house_number) parts.push(addr.house_number);
        if (addr.village || addr.town || addr.city) {
          parts.push(addr.village || addr.town || addr.city);
        }
        if (addr.country) parts.push(addr.country);
        
        return parts.length > 0 ? parts.join(", ") : data.display_name || null;
      } catch {
        return null;
      }
    },
    enabled: gpsHasFix && !!gps?.lat && !!gps?.lon,
    staleTime: 60000, // Cache for 1 minute (addresses don't change quickly)
    retry: 1,
  });

  useEffect(() => {
    if (address) setLastAddress(address);
  }, [address]);

  const modules: Record<OverviewModuleId, JSX.Element> = {
    gps_card: (
      <Card
        className={`glass-card p-0 h-full card-compact ${terrainClass} relative overflow-hidden flex flex-col`}
        style={{ ["--gps-photo" as any]: `url(${gpsBg})` }}
      >
        <CardHeader className="pb-2 px-4 pt-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <div className="p-2 rounded-lg bg-secondary/40 border border-glass">
                <MapPin className="h-4 w-4 text-primary icon-glow" />
              </div>
              GPS Status
            </CardTitle>
            {!gpsHasFix && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="text-xs text-muted-foreground px-2 py-1 rounded-full border border-glass bg-secondary/40">
                      Last update
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="text-xs text-muted-foreground">
                      Last GPS update {formatTimeAgo(gps?.ts ?? null)}
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-3 px-4 pb-6 pt-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={gpsHasFix ? "status-dot-online" : "status-dot-warning"} />
              <span className="text-sm text-muted-foreground">Signal</span>
            </div>
            <span className={`text-sm font-medium ${gpsHasFix ? "text-success" : "text-warning"}`}>
              {gpsHasFix ? "Strong" : "Weak"}
            </span>
          </div>

          <div className="mt-auto space-y-3">
            <div className="flex items-center justify-between pt-2 border-t border-glass">
              <div className="flex items-center gap-2">
                <Gauge className="w-4 h-4 text-primary" />
                <span className="text-sm text-muted-foreground">Speed</span>
              </div>
              <span className="text-lg font-bold text-primary">
                {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-primary" />
                <span className="text-sm text-muted-foreground">Altitude</span>
              </div>
              <span className="text-lg font-bold text-foreground">
                {altitudeM != null ? `${Math.round(altitudeM)} m` : "—"}
              </span>
            </div>

            <div className="space-y-2">
              <p className="metric-label">Approx Location</p>
              <div className="flex items-start gap-2 text-sm font-semibold text-foreground">
                <MapPin className="mt-0.5 h-3.5 w-3.5 text-primary" />
                <span>{address ?? lastAddress ?? "—"}</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    ),
    temp_card: (
      <Card className={`glass-card p-0 h-full card-compact temp-card ${tempClass(kombiT)} flex flex-col`}>
        <CardHeader className="pb-2 px-4 pt-4">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <Thermometer className="h-4 w-4 text-primary" />
            </div>
            Temperature
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col gap-3 px-4 pb-4 pt-0">
          {import.meta.env.DEV && (
            <div className="text-xs text-primary p-1.5 bg-secondary/40 rounded-lg border border-glass mb-1">
              <strong>Debug:</strong> temps = {temps ? JSON.stringify(temps, null, 2) : "null"}
            </div>
          )}
          <div className="mt-auto space-y-3">
            {(() => {
              const t = temps?.kombi?.temp_c ?? null;
              const style = tempStyle(t);
              const hum = temps?.kombi?.hum_pct ?? null;
              return (
                <div className={`temp-tile ${style.card}`}>
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-secondary/40 border border-glass">
                      <Home className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Kombi</p>
                      <p className="text-sm text-muted-foreground">Interior</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <style.Icon className={`w-5 h-5 ${style.text}`} />
                      <span className={`text-2xl font-bold ${style.text}`}>
                        {t != null ? t.toFixed(1) : "—"}
                      </span>
                      <span className="text-xs text-muted-foreground">°C</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="rounded-full px-2 py-0.5 text-xs bg-secondary/40 border border-glass text-muted-foreground">
                        {tempLabel(t)}
                      </div>
                      {hum != null && (
                        <div className="rounded-full px-2 py-0.5 text-xs bg-secondary/40 border border-glass text-muted-foreground">
                          {Math.round(hum)}%
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
            {(() => {
              const t = temps?.garaza?.temp_c ?? null;
              const style = tempStyle(t);
              const hum = temps?.garaza?.hum_pct ?? null;
              return (
                <div className={`temp-tile ${style.card}`}>
                  <div className="flex items-center gap-2">
                    <div className="p-2 rounded-lg bg-secondary/40 border border-glass">
                      <Warehouse className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-wide text-muted-foreground">Garaža</p>
                      <p className="text-sm text-muted-foreground">Storage</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <style.Icon className={`w-5 h-5 ${style.text}`} />
                      <span className={`text-2xl font-bold ${style.text}`}>
                        {t != null ? t.toFixed(1) : "—"}
                      </span>
                      <span className="text-xs text-muted-foreground">°C</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="rounded-full px-2 py-0.5 text-xs bg-secondary/40 border border-glass text-muted-foreground">
                        {tempLabel(t)}
                      </div>
                      {hum != null && (
                        <div className="rounded-full px-2 py-0.5 text-xs bg-secondary/40 border border-glass text-muted-foreground">
                          {Math.round(hum)}%
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>
        </CardContent>
      </Card>
    ),
    weather_card: (
      <Card className={`glass-card p-0 h-full card-compact weather-card ${weatherMeta.theme}`}>
        <CardHeader className="pb-2 px-4 pt-4">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <WeatherIcon className="h-4 w-4 text-primary" />
            </div>
            Weather Forecast
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 px-4 pb-4 pt-0">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Outside Now</p>
              <p className="text-3xl font-bold text-foreground">
                {currentOutsideTemp != null ? currentOutsideTemp.toFixed(1) : "—"}°C
              </p>
              <p className="text-sm text-muted-foreground">{weatherMeta.label}</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-muted-foreground">Wind</p>
              <p className="text-lg font-semibold">
                {currentForecast?.wind_kmh != null ? `${currentForecast.wind_kmh.toFixed(0)} km/h` : "—"}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 forecast-grid">
            {forecastDays.map((d) => (
              <ForecastChip
                key={d.date}
                day={new Date(d.date).toLocaleDateString(undefined, { weekday: "short" })}
                max={d.temp_max}
                min={d.temp_min}
                code={d.weather_code ?? null}
              />
            ))}
          </div>

          {weatherMeta.theme === "weather-sun" && <div className="sun-pulse" />}
          {weatherMeta.theme === "weather-rain" && (
            <div className="rain-drops">
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
          )}
          {weatherMeta.theme === "weather-snow" && (
            <div className="snow-flakes">
              <span />
              <span />
              <span />
              <span />
              <span />
              <span />
            </div>
          )}
          {weatherMeta.theme === "weather-storm" && <div className="storm-bolt" />}
        </CardContent>
      </Card>
    ),
    water_card: <WaterLevelCard />,
    battery: (
      <Card className="glass-card p-0 h-full card-compact battery-card">
        <CardHeader className="pb-2 px-4 pt-4">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/20 border border-glass">
              <Battery className="h-4 w-4 text-primary" />
            </div>
            Battery
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 px-4 pb-4 pt-0">
          <div className="flex items-end justify-between">
            <div className="flex items-baseline gap-1">
              <span className="text-3xl font-bold text-muted-foreground">—</span>
              <span className="text-lg text-muted-foreground">%</span>
            </div>
            <div className="text-sm text-muted-foreground">Status</div>
          </div>
          <div className="grid grid-cols-2 gap-4 pt-2 border-t border-glass">
            <div>
              <p className="metric-label">Voltage</p>
              <p className="text-lg font-semibold">— V</p>
            </div>
            <div>
              <p className="metric-label">Health</p>
              <p className="text-lg font-semibold text-muted-foreground">Unknown</p>
            </div>
          </div>
        </CardContent>
      </Card>
    ),
    header_relay: <HeaderRelayCard />,
    relay_rules: <RelayRulesWidget />,
    gps_map: (
      <Card className="glass-card p-0 h-full card-compact gps-map-card flex flex-col">
        <CardHeader className="pb-3 px-4 pt-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <Activity className="h-4 w-4 text-primary" />
              </div>
              <div>
                <CardTitle className="text-lg font-semibold text-foreground">GPS Track</CardTitle>
                <p className="text-sm text-muted-foreground mt-1">Last 24 hours location history</p>
              </div>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-secondary/40 border border-glass">
              <span className="text-xs font-medium text-foreground/80">Live</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex-1 flex flex-col px-4 pb-4 pt-0">
          <div className="flex-1 flex flex-col lg:flex-row gap-4">
            <div className="flex-1 min-w-0">
              <GpsTrackMap data={track} currentLat={gps?.lat ?? null} currentLon={gps?.lon ?? null} />
            </div>
            <div className="w-full lg:w-56 flex flex-col gap-3">
              <div className="p-3 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Track Points</p>
                <p className="text-xl font-bold text-primary">{track?.count ?? 0}</p>
              </div>
              <div className="p-3 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">Current Speed</p>
                <p className="text-xl font-bold">{speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}</p>
              </div>
              <div className="p-3 rounded-xl bg-secondary/30 border border-glass">
                <p className="metric-label">GPS Status</p>
                <p className={`text-xl font-bold ${gpsHasFix ? "text-success" : "text-warning"}`}>{gpsStatus}</p>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    ),
  };

  const hidden = new Set(layout.hidden);
  const topIds = layout.topOrder.filter((id) => !hidden.has(id));
  const bottomIds = layout.bottomOrder.filter((id) => !hidden.has(id));

  const orderedIds = [...topIds, ...bottomIds];
  const gridColsClass =
    layout.columns === 5
      ? "lg:grid-cols-4 xl:grid-cols-5"
      : layout.columns === 4
      ? "lg:grid-cols-4"
      : "lg:grid-cols-3";
  const gridDensityClass = layout.columns === 5 ? "overview-cols-5" : "";

  return (
    <div className="space-y-6">
      <div className={`grid grid-cols-1 md:grid-cols-2 ${gridColsClass} gap-4 lg:gap-6 auto-rows-[minmax(0,300px)] items-stretch ${gridDensityClass}`}>
        {orderedIds.map((id) => (
          <div
            key={id}
            className={`min-w-0 h-full ${id === "gps_map" ? "lg:col-span-3" : ""}`}
          >
            {modules[id]}
          </div>
        ))}
      </div>
    </div>
  );
}
