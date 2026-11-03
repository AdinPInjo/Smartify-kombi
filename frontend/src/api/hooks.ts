import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  ClimatePoint,
  ClimateSnapshot,
  Energy,
  EnergyPoint,
  GpsArchive,
  GpsDistance,
  GpsState,
  Health,
  LogEntry,
  Me,
  OnOff,
  Relay,
  RelayEvent,
  Rule,
  RulesResponse,
  SystemStatus,
  TrackPoint,
  WaterPoint,
  WaterReading,
  WaterSettings,
  Weather,
  WifiNetwork,
  WifiStatus,
} from "./types";

// Live values refresh every few seconds; history less often.
const LIVE = 5_000;
const SLOW = 60_000;

export const useHealth = () =>
  useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/health"), refetchInterval: 15_000 });

/** Remote dashboard (cloud/) or the van's own? Some features exist only on the van. */
export function useMode() {
  const health = useHealth();
  const cloud = health.data?.mode === "cloud";
  return { cloud, device: health.data?.device, ready: health.isSuccess };
}

export const useMe = () =>
  useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/auth/me"), retry: false });

export const useRelays = () =>
  useQuery({
    queryKey: ["relays"],
    queryFn: () => api.get<{ relays: Relay[] }>("/relays").then((r) => r.relays),
    refetchInterval: LIVE,
  });

export const useRelay = (id: string) =>
  useQuery({ queryKey: ["relays", id], queryFn: () => api.get<Relay>(`/relays/${id}`), refetchInterval: LIVE });

export const useRelayEvents = (id: string) =>
  useQuery({
    queryKey: ["relays", id, "events"],
    queryFn: () => api.get<{ events: RelayEvent[] }>(`/relays/${id}/events?limit=30`).then((r) => r.events),
    refetchInterval: LIVE * 2,
  });

export const useRules = (relayId: string) =>
  useQuery({
    queryKey: ["rules", relayId],
    queryFn: () => api.get<RulesResponse>(`/relays/${relayId}/rules`),
    refetchInterval: LIVE,
  });

export const useClimate = () =>
  useQuery({
    queryKey: ["climate"],
    queryFn: () => api.get<{ sensors: ClimateSnapshot[] }>("/climate").then((r) => r.sensors),
    refetchInterval: LIVE,
  });

export const useClimateHistory = (sensor: string | undefined, hours: number) =>
  useQuery({
    queryKey: ["climate", sensor, hours],
    queryFn: () =>
      api.get<{ points: ClimatePoint[] }>(`/climate/${sensor}/history?hours=${hours}`).then((r) => r.points),
    enabled: Boolean(sensor),
    refetchInterval: SLOW,
  });

export const useWater = () =>
  useQuery({ queryKey: ["water"], queryFn: () => api.get<WaterReading>("/water"), refetchInterval: LIVE });

export const useWaterHistory = (hours: number) =>
  useQuery({
    queryKey: ["water", "history", hours],
    queryFn: () => api.get<{ points: WaterPoint[] }>(`/water/history?hours=${hours}`).then((r) => r.points),
    refetchInterval: SLOW,
  });

export const useWaterSettings = () =>
  useQuery({ queryKey: ["water", "settings"], queryFn: () => api.get<WaterSettings>("/water/settings") });

export const useEnergy = () =>
  useQuery({ queryKey: ["energy"], queryFn: () => api.get<Energy>("/energy"), refetchInterval: LIVE });

export const useEnergyHistory = (hours: number) =>
  useQuery({
    queryKey: ["energy", "history", hours],
    queryFn: () => api.get<{ points: EnergyPoint[] }>(`/energy/history?hours=${hours}`).then((r) => r.points),
    refetchInterval: SLOW,
  });

export const useGps = () =>
  useQuery({ queryKey: ["gps"], queryFn: () => api.get<GpsState>("/gps"), refetchInterval: LIVE });

export const useTrack = (hours: number) =>
  useQuery({
    queryKey: ["gps", "track", hours],
    queryFn: () => api.get<{ points: TrackPoint[] }>(`/gps/track?hours=${hours}`).then((r) => r.points),
    refetchInterval: SLOW,
  });

export const useDistance = () =>
  useQuery({ queryKey: ["gps", "distance"], queryFn: () => api.get<GpsDistance>("/gps/distance"), refetchInterval: SLOW });

export const useGpsArchives = () =>
  useQuery({
    queryKey: ["gps", "archive"],
    queryFn: () => api.get<{ files: GpsArchive[] }>("/gps/archive").then((r) => r.files),
  });

export const useWeather = () =>
  useQuery({ queryKey: ["weather"], queryFn: () => api.get<Weather>("/weather"), refetchInterval: SLOW });

export const useWifi = () =>
  useQuery({ queryKey: ["wifi"], queryFn: () => api.get<WifiStatus>("/wifi"), refetchInterval: LIVE * 3, retry: false });

export const useWifiNetworks = (enabled: boolean) =>
  useQuery({
    queryKey: ["wifi", "networks"],
    queryFn: () => api.get<{ networks: WifiNetwork[] }>("/wifi/networks").then((r) => r.networks),
    enabled,
  });

export const useSystem = () =>
  useQuery({ queryKey: ["system"], queryFn: () => api.get<SystemStatus>("/system"), refetchInterval: LIVE * 2 });

/** Pass an empty level to disable (e.g. on the remote dashboard, which has no log). */
export const useLogs = (level: string) =>
  useQuery({
    queryKey: ["logs", level],
    queryFn: () => api.get<{ logs: LogEntry[] }>(`/logs?limit=300&level=${level}`).then((r) => r.logs),
    refetchInterval: LIVE,
    enabled: level !== "",
  });

// --- mutations ------------------------------------------------------------------

/** Relay control: manual on/off (optionally timed) or back to automatic. */
export function useSetRelayMode() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, mode, durationMinutes }: { id: string; mode: "auto" | OnOff; durationMinutes?: number }) =>
      mode === "auto"
        ? api.post<Relay>(`/relays/${id}/auto`)
        : api.post<Relay>(`/relays/${id}/manual`, { state: mode, duration_minutes: durationMinutes }),
    onSuccess: (relay) => {
      client.setQueryData<Relay[]>(["relays"], (old) => old?.map((r) => (r.id === relay.id ? relay : r)));
      client.setQueryData(["relays", relay.id], relay);
      client.invalidateQueries({ queryKey: ["rules", relay.id] });
    },
  });
}

export function useUpdateRelay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<Relay> }) => api.patch<Relay>(`/relays/${id}`, changes),
    onSuccess: () => client.invalidateQueries({ queryKey: ["relays"] }),
  });
}

export function useCreateRelay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; gpio_pin: number; label?: string; active_low?: boolean }) =>
      api.post<Relay>("/relays", body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["relays"] }),
  });
}

export function useDeleteRelay() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<Relay>(`/relays/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["relays"] }),
  });
}

export type RuleInput = Pick<Rule, "name" | "condition" | "action" | "priority" | "cooldown_seconds" | "enabled">;

export function useSaveRule(relayId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, rule }: { id?: string; rule: Partial<RuleInput> }) =>
      id ? api.patch<Rule>(`/rules/${id}`, rule) : api.post<Rule>(`/relays/${relayId}/rules`, rule),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["rules", relayId] });
      client.invalidateQueries({ queryKey: ["relays"] });
    },
  });
}

export function useDeleteRule(relayId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<Rule>(`/rules/${id}`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["rules", relayId] });
      client.invalidateQueries({ queryKey: ["relays"] });
    },
  });
}

export function useUpdateWaterSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: Partial<WaterSettings>) => api.patch<WaterSettings>("/water/settings", changes),
    onSuccess: (settings) => {
      client.setQueryData(["water", "settings"], settings);
      client.invalidateQueries({ queryKey: ["water"] });
    },
  });
}

export function useCalibrateWater() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (point: "empty" | "full") => api.post<WaterSettings>("/water/calibrate", { point }),
    onSuccess: (settings) => {
      client.setQueryData(["water", "settings"], settings);
      client.invalidateQueries({ queryKey: ["water"] });
    },
  });
}

export function useWifiConnect() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { ssid: string; password?: string }) => api.post<WifiStatus>("/wifi/connect", body),
    onSuccess: (status) => {
      client.setQueryData(["wifi"], status);
      client.invalidateQueries({ queryKey: ["wifi", "networks"] });
    },
  });
}
