import { useEffect, useMemo, useRef, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { MapPin, Navigation, Car, Warehouse, Thermometer, Battery, Power, Droplet, Activity, TrendingUp, Plus, Trash2, Save, Settings2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/utils";
import { getOverviewLayout, OverviewModuleId } from "@/lib/overviewLayout";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

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

  return <div ref={elRef} className="h-32 w-full rounded-xl overflow-hidden border border-zinc-800/50" />;
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

  return <div ref={elRef} className="h-[420px] w-full rounded-xl overflow-hidden border border-zinc-800/50" />;
}

function HeaderRelayCard() {
  const queryClient = useQueryClient();

  // Fetch heater relay from new API
  const { data: relaysResponse, isLoading, error } = useQuery({
    queryKey: ["relays"],
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
      return result;
    },
    onError: (error) => {
      console.error("[HeaderRelayCard] Failed to toggle relay:", error);
      toast.error("Failed to toggle relay", {
        description: error instanceof Error ? error.message : "Unknown error occurred",
      });
      queryClient.invalidateQueries({ queryKey: ["relays"] });
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
    <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:border-zinc-700/50 hover:shadow-xl hover:shadow-zinc-900/20">
      <div className="absolute inset-0 bg-gradient-to-br from-orange-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      <CardHeader className="pb-3 relative z-10">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/20">
            <Power className="h-4 w-4 text-orange-400" />
          </div>
          Header ON-OFF
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 relative z-10">
        <div className="flex items-center justify-between">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-zinc-200">Relay Control</span>
              {isManual ? (
                <span className="text-xs px-2 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/20">
                  Manual
                </span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
                  Auto
                </span>
              )}
            </div>
            {error ? (
              <span className="text-xs text-red-400">Offline</span>
            ) : isUpdating ? (
              <span className="text-xs text-zinc-400">Updating...</span>
            ) : (
              <span className={`text-xs ${isOn ? "text-emerald-400" : "text-zinc-400"}`}>
                {isOn ? "ON" : "OFF"}
              </span>
            )}
            {manualUntil && manualUntil > Date.now() / 1000 && (
              <span className="text-xs text-zinc-500">
                Manual until {new Date(manualUntil * 1000).toLocaleTimeString()}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {isUpdating && (
              <div className="h-4 w-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
            )}
            {isPending && !isUpdating && (
              <div className="h-4 w-4 border-2 border-zinc-500 border-t-transparent rounded-full animate-spin opacity-50" />
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <div>
                    <Switch
                      checked={isOn}
                      onCheckedChange={handleToggle}
                      disabled={isDisabled}
                      className="data-[state=checked]:bg-orange-500 data-[state=unchecked]:bg-zinc-700"
                    />
                  </div>
                </TooltipTrigger>
                {isPending && (
                  <TooltipContent>
                    <p className="text-sm font-medium">
                      {pendingMessage}
                      {cooldownRemaining !== null && cooldownRemaining > 0 && (
                        <span className="ml-1 text-orange-400">({cooldownRemaining}s)</span>
                      )}
                    </p>
                    {sensorSampleCount !== null && relaysResponse?.sensor_sample_count !== undefined && (
                      <p className="text-xs text-zinc-400 mt-1">
                        Progress: {sensorSampleCount}/6 samples collected
                      </p>
                    )}
                    <p className="text-xs text-zinc-400 mt-1">
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
            className="w-full bg-zinc-800/50 border-zinc-700/50 text-zinc-300 hover:bg-zinc-700/50"
            onClick={handleReturnToAuto}
            disabled={isDisabled || isPending}
          >
            Return to Auto
          </Button>
        )}
        {error && (
          <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded px-2 py-1">
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

  return (
    <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-blue-950/30 to-blue-900/20 backdrop-blur-sm transition-all duration-300 hover:border-blue-700/50 hover:shadow-xl hover:shadow-blue-900/20 flex-1">
      <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      <CardHeader className="pb-3 relative z-10">
        <CardTitle className="text-sm font-medium text-zinc-300 flex items-center gap-2">
          <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
            <Droplet className="h-4 w-4 text-blue-400" />
          </div>
          Water Level
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm py-2 relative z-10">
        <div className="flex items-center justify-between">
          <span className="text-zinc-400">Level</span>
          <span className="font-semibold text-zinc-200">
            {levelPercent !== null ? `${levelPercent}%` : "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-zinc-400">Status</span>
          <span className={`font-semibold ${
            waterData?.status === "error" || waterData?.status === "stale"
              ? "text-amber-400"
              : waterData?.status === "ok"
              ? "text-zinc-200"
              : "text-zinc-400"
          }`}>
            {waterData?.message ?? "—"}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

function RelayRulesWidget() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Fetch heater relay
  const { data: relaysResponse } = useQuery({
    queryKey: ["relays"],
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
    <Card className="group relative overflow-hidden border-zinc-800/50 bg-gradient-to-br from-zinc-900/50 to-zinc-950/50 backdrop-blur-sm transition-all duration-300 hover:shadow-xl hover:shadow-zinc-900/20">
      <div className="absolute inset-0 bg-gradient-to-br from-purple-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      <CardHeader className="pb-4 relative z-10">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg font-semibold text-zinc-200 flex items-center gap-2">
              <Settings2 className="h-5 w-5 text-purple-400" />
              Relay Rules
            </CardTitle>
            <p className="text-sm text-zinc-400 mt-1">
              {enabledRules.length} active rule{enabledRules.length !== 1 ? "s" : ""}
            </p>
          </div>
          <Button
            size="sm"
            className="bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 text-purple-400"
            onClick={() => navigate("/dashboard/relays")}
          >
            <Plus className="h-4 w-4 mr-1.5" />
            Manage
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 relative z-10">
        {lastFiredRule && (
          <div className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 p-3 backdrop-blur-sm">
            <div className="text-xs text-zinc-400 mb-1">Last fired</div>
            <div className="text-sm font-medium text-zinc-200">{lastFiredRule.name}</div>
            <div className="text-xs text-zinc-500 mt-1">{formatTimeAgo(lastFiredRule.last_triggered_at)}</div>
          </div>
        )}

        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {isLoading ? (
            <div className="text-sm text-zinc-400 text-center py-4">Loading rules...</div>
          ) : rules.length === 0 ? (
            <div className="rounded-lg border-2 border-dashed border-zinc-700/30 p-8 text-center">
              <Settings2 className="h-8 w-8 text-zinc-600 mx-auto mb-2" />
              <p className="text-sm text-zinc-500">No rules configured</p>
              <p className="text-xs text-zinc-600 mt-1">Click "Manage" to create automation rules</p>
            </div>
          ) : (
            rules.slice(0, 3).map((rule: any) => (
              <div key={rule.id} className="rounded-lg bg-zinc-800/30 border border-zinc-700/30 p-3 backdrop-blur-sm">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-semibold text-zinc-200">{rule.name}</span>
                      {rule.is_enabled ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          Active
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
                          Disabled
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-400">{formatRuleDescription(rule)}</p>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        {rules.length > 3 && (
          <Button
            variant="outline"
            size="sm"
            className="w-full bg-zinc-800/50 border-zinc-700/50 text-zinc-300 hover:bg-zinc-700/50"
            onClick={() => navigate("/dashboard/relays")}
          >
            View all {rules.length} rules
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function OverviewDashboard() {
  const [track, setTrack] = useState<TrackPayload | null>(null);
  const [layout, setLayout] = useState(getOverviewLayout());

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

  const modules: Record<OverviewModuleId, JSX.Element> = {
    gps_card: (
      <Card className="glass-card">
        <CardHeader className="pb-3 relative z-10">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/20 border border-glass">
                <MapPin className="h-4 w-4 text-primary icon-glow" />
              </div>
              Van Location
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 relative z-10">
          <GpsMiniMap lat={gps?.lat ?? null} lon={gps?.lon ?? null} />

          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Status</span>
              <span className={`font-semibold ${gpsHasFix ? "text-success" : "text-warning"}`}>
                {gpsStatus}
              </span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Location</span>
              <span className="font-medium text-xs text-right max-w-[60%] truncate text-foreground/80" title={address || undefined}>
                {gpsHasFix ? (address || `${gps?.lat?.toFixed(4)}, ${gps?.lon?.toFixed(4)}`) : "—"}
              </span>
            </div>

            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground flex items-center gap-2">
                <Navigation className="h-3.5 w-3.5" />
                Speed
              </span>
              <span className="font-semibold tabular-nums text-foreground">
                {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    ),
    temp_card: (
      <Card className={`glass-card ${tempClass(kombiT)}`}>
        <CardContent className="flex flex-col space-y-3 py-4 relative z-10">
          {import.meta.env.DEV && (
            <div className="text-xs text-primary p-1.5 bg-secondary/40 rounded-lg border border-glass mb-1">
              <strong>Debug:</strong> temps = {temps ? JSON.stringify(temps, null, 2) : "null"}
            </div>
          )}

          <div className="flex items-center justify-between rounded-lg bg-secondary/40 border border-glass px-4 py-3 backdrop-blur-sm transition-all hover:bg-secondary/60">
            <span className="flex items-center gap-2.5 text-foreground/80">
              <Car className="h-4 w-4 text-primary" />
              <span className="font-medium">Kombi</span>
            </span>
            <div className="flex items-center gap-2">
              <span className="font-bold tabular-nums text-lg text-foreground">
                {formatTemp(temps?.kombi?.temp_c ?? null)}
              </span>
              <span className="text-xs text-muted-foreground">{formatHum(temps?.kombi?.hum_pct ?? null)}</span>
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg bg-secondary/40 border border-glass px-4 py-3 backdrop-blur-sm transition-all hover:bg-secondary/60">
            <span className="flex items-center gap-2.5 text-foreground/80">
              <Warehouse className="h-4 w-4 text-warning" />
              <span className="font-medium">Garaža</span>
            </span>
            <div className="flex items-center gap-2">
              <span className="font-bold tabular-nums text-lg text-foreground">
                {formatTemp(temps?.garaza?.temp_c ?? null)}
              </span>
              <span className="text-xs text-muted-foreground">{formatHum(temps?.garaza?.hum_pct ?? null)}</span>
            </div>
          </div>
        </CardContent>
      </Card>
    ),
    water_card: <WaterLevelCard />,
    battery: (
      <Card className="glass-card">
        <CardHeader className="pb-3 relative z-10">
          <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
            <div className="p-2 rounded-lg bg-secondary/50 border border-glass">
              <Battery className="h-4 w-4 text-success" />
            </div>
            Battery
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 relative z-10">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">State of charge</span>
            <span className="font-semibold text-foreground">— %</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Voltage</span>
            <span className="font-semibold text-foreground">— V</span>
          </div>
        </CardContent>
      </Card>
    ),
    header_relay: <HeaderRelayCard />,
    relay_rules: <RelayRulesWidget />,
    gps_map: (
      <Card className="glass-card">
        <CardHeader className="pb-4 relative z-10">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-lg font-semibold text-foreground">GPS Map & Track</CardTitle>
              <p className="text-sm text-muted-foreground mt-1">Last 24 hours location history</p>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-secondary/40 border border-glass">
              <Activity className="h-4 w-4 text-primary" />
              <span className="text-xs font-medium text-foreground/80">Live</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 relative z-10">
          <GpsTrackMap data={track} currentLat={gps?.lat ?? null} currentLon={gps?.lon ?? null} />

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-lg bg-secondary/40 border border-glass px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Track Points</span>
                <span className="font-bold text-lg tabular-nums text-foreground">{track?.count ?? 0}</span>
              </div>
            </div>
            <div className="rounded-lg bg-secondary/40 border border-glass px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Current Speed</span>
                <span className="font-bold text-lg tabular-nums text-foreground">
                  {speedKmh == null ? "—" : `${speedKmh.toFixed(1)} km/h`}
                </span>
              </div>
            </div>
            <div className="rounded-lg bg-secondary/40 border border-glass px-4 py-3 backdrop-blur-sm">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">GPS Status</span>
                <span className={`font-bold text-lg ${gpsHasFix ? "text-success" : "text-warning"}`}>
                  {gpsStatus}
                </span>
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Dashboard Overview</h1>
          <p className="text-sm text-zinc-400 mt-1">Real-time monitoring of your van systems</p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {topIds.map((id) => (
          <div key={id} className="min-w-0">
            {modules[id]}
          </div>
        ))}
      </div>

      {/* Relay Rules + GPS Map Section */}
      <div className="grid gap-6 lg:grid-cols-2">
        {bottomIds.map((id) => (
          <div key={id} className="min-w-0">
            {modules[id]}
          </div>
        ))}
      </div>
    </div>
  );
}
