// Types mirroring the backend API (backend/smartify/api). Keep them in sync.

export type OnOff = "on" | "off";

export interface Health {
  ok: boolean;
  version: string;
  hardware: "pi" | "mock";
  schema_version: number;
  server_time: number;
  /** Absent on the Pi; "cloud" on the remote dashboard. */
  mode?: "device" | "cloud";
  device?: { last_seen: number | null; online: boolean; version: string | null };
}

export interface Me {
  user: string;
  default_credentials: boolean;
}

export interface Relay {
  id: string;
  name: string;
  label: string | null;
  gpio_pin: number;
  active_low: boolean;
  enabled: boolean;
  mode: "auto" | "manual";
  manual_state: OnOff | null;
  manual_until: number | null;
  min_on_seconds: number;
  min_off_seconds: number;
  cutoff_sensor: string | null;
  cutoff_max_c: number | null;
  state: OnOff;
  changed_at: number;
  source: string;
  reason: string | null;
  rule_id: string | null;
  updated_at: number;
  revision: number;
  last_error: string | null;
  pending: string | null;
  explanation: string | null;
  /** Remote dashboard only: a change on its way to the van, or why it was not applied. */
  remote?: string | null;
}

export interface RelayEvent {
  id: number;
  relay_id: string;
  source: string;
  rule_id: string | null;
  old_state: OnOff | null;
  new_state: OnOff;
  reason: string | null;
  created_at: number;
}

export type Metric =
  | "temperature"
  | "humidity"
  | "battery_soc"
  | "battery_voltage"
  | "battery_current"
  | "solar_power"
  | "water_level"
  | "speed";

export type Condition =
  | { type: "threshold"; metric: Metric; sensor: string; op: "<" | "<=" | ">" | ">="; value: number }
  | { type: "range"; metric: Metric; sensor: string; min: number; max: number }
  | { type: "all"; conditions: Condition[] }
  | { type: "any"; conditions: Condition[] }
  | { type: "not"; condition: Condition }
  | { type: "always" }
  /** Local time window; may cross midnight. days: 0 = Monday. */
  | { type: "time"; from: string; to: string; days?: number[] };

export interface RuleStatus {
  matched: boolean;
  issue: "warming_up" | "stale" | "missing" | null;
  values: Record<string, number>;
  is_winner: boolean;
}

export interface Rule {
  id: string;
  relay_id: string;
  name: string;
  enabled: boolean;
  priority: number;
  condition: Condition;
  action: OnOff;
  cooldown_seconds: number;
  last_triggered_at: number | null;
  created_at: number;
  updated_at: number;
  revision: number;
  status?: RuleStatus | null;
}

export interface RulesResponse {
  rules: Rule[];
  decision: { state: OnOff | null; reason: string };
  mode: "auto" | "manual";
}

export interface ClimateSnapshot {
  sensor: string;
  status: "ready" | "warming_up" | "stale";
  temperature_c: number | null;
  humidity: number | null;
  sample_count: number;
  last_good_at: number | null;
  last_error: string | null;
}

export interface ClimatePoint {
  created_at: number;
  temperature_c: number | null;
  humidity: number | null;
}

export interface WaterReading {
  ok: boolean;
  level_percent: number | null;
  battery_voltage: number | null;
  signal_voltage: number | null;
  ratio: number | null;
  error: string | null;
  updated_at: number | null;
}

export interface WaterSettings {
  method: "voltage" | "ratio";
  signal_channel: number;
  supply_channel: number;
  divider_r_top: number;
  divider_r_bottom: number;
  empty_voltage: number;
  full_voltage: number;
  empty_ratio: number;
  full_ratio: number;
  updated_at: number;
  revision: number;
}

export interface WaterPoint {
  created_at: number;
  level_percent: number | null;
  battery_voltage: number | null;
}

export interface GpsFix {
  lat: number;
  lon: number;
  speed_kmh: number | null;
  course: number | null;
  altitude_m: number | null;
  satellites: number | null;
  hdop?: number | null;
}

export interface GpsState {
  status: "disabled" | "no_device" | "no_fix" | "ok";
  fix: GpsFix | null;
  fix_at: number | null;
  error: string | null;
  /** Standing still: `fix` is the smoothed parked position. */
  parked?: boolean;
  parked_since?: number | null;
}

export interface Stop {
  id: number;
  lat: number;
  lon: number;
  arrived_at: number;
  left_at: number | null;
  place: string | null;
  country: string | null;
  here_now: boolean;
  nights: number;
  duration_seconds: number;
  km_from_previous: number | null;
}

export interface EnergyForecast {
  available: boolean;
  reason: string | null;
  soc_now?: number | null;
  min_soc?: number | null;
  min_at?: number | null;
  low_at?: number | null;
  load_w?: number | null;
  solar_peak_w?: number | null;
  solar_wh_24h?: number | null;
  capacity_ah?: number | null;
  capacity_estimated?: boolean;
  points?: { ts: number; soc: number }[];
}

export type NotifyChannel = "ntfy" | "telegram";

interface AlertToggle {
  enabled: boolean;
}
interface ThresholdAlert extends AlertToggle {
  threshold: number;
}

export interface NotificationSettings {
  channels: {
    ntfy: { enabled: boolean; server: string; topic: string; token: string; token_set: boolean };
    telegram: { enabled: boolean; bot_token: string; bot_token_set: boolean; chat_id: string };
  };
  alerts: {
    battery_low: ThresholdAlert;
    battery_not_charging: AlertToggle;
    cold_inside: ThresholdAlert & { sensor: string };
    hot_inside: ThresholdAlert & { sensor: string };
    water_low: ThresholdAlert;
    sensor_fault: AlertToggle;
    relay_cutoff: AlertToggle;
    departure: AlertToggle & {
      after_minutes: number;
      night_only: boolean;
      night_from: string;
      night_to: string;
      paused_until: number | null;
    };
    frost_forecast: ThresholdAlert;
    energy_forecast: ThresholdAlert & { battery_capacity_ah: number | null; solar_peak_w: number | null };
  };
  quiet_hours: { enabled: boolean; from: string; to: string };
  repeat_hours: number;
  active_channels: NotifyChannel[];
}

export interface NotificationEntry {
  id: number;
  alert: string;
  title: string;
  message: string;
  priority: "low" | "default" | "high" | "urgent";
  status: "queued" | "sent" | "dropped";
  last_error: string | null;
  attempts: number;
  created_at: number;
  sent_at: number | null;
  next_attempt_at: number;
}

export interface TrackPoint {
  created_at: number;
  lat: number;
  lon: number;
  speed_kmh: number | null;
}

export interface GpsDistance {
  total_km: number;
  days: { day: string; distance_km: number }[];
}

export interface GpsArchive {
  name: string;
  bytes: number;
  updated_at: number;
}

export interface EnergyDevice {
  device: string;
  kind: string;
  model: string | null;
  values: Record<string, number | string | null>;
  rssi: number | null;
  updated_at: number;
  stale: boolean;
}

export interface Energy {
  available: boolean;
  battery: {
    voltage: number | null;
    current: number | null;
    power: number | null;
    soc: number | null;
    remaining_mins: number | null;
    consumed_ah: number | null;
    starter_voltage: number | null;
    alarm: string | null;
  };
  solar: {
    power: number | null;
    yield_today_wh: number | null;
    charge_state: string | null;
    error: string | null;
  } | null;
  dcdc: {
    charge_state: string | null;
    input_voltage: number | null;
    output_voltage: number | null;
    output_current: number | null;
    off_reason: string | null;
  } | null;
  inverter: {
    state: string | null;
    ac_in_state: string | null;
    ac_in_power: number | null;
    ac_out_power: number | null;
    alarm: string | null;
  } | null;
  devices: EnergyDevice[];
}

export interface EnergyPoint {
  created_at: number;
  battery_voltage: number | null;
  battery_current: number | null;
  battery_soc: number | null;
  solar_power: number | null;
  solar_yield_today: number | null;
  dcdc_output_current: number | null;
  ac_out_power: number | null;
}

export interface Weather {
  available: boolean;
  updated_at: number | null;
  error: string | null;
  temperature_c?: number | null;
  humidity?: number | null;
  wind_kmh?: number | null;
  weather_code?: number | null;
  forecast?: {
    date: string;
    temperature_max: number;
    temperature_min: number;
    precipitation_mm: number;
    weather_code: number;
  }[];
}

export interface WifiStatus {
  available: boolean;
  connected: boolean;
  ssid: string | null;
  ip_address: string | null;
  error: string | null;
}

export interface WifiNetwork {
  ssid: string;
  signal: number;
  secured: boolean;
  in_use: boolean;
}

export interface WorkerStatus {
  name: string;
  running: boolean;
  interval_seconds: number;
  runs: number;
  last_run_at: number | null;
  last_error: string | null;
  last_error_at: number | null;
}

export interface SystemStatus {
  version: string;
  hardware: "pi" | "mock";
  uptime_seconds: number;
  server_time: number;
  cpu_temperature_c: number | null;
  load_average: number | null;
  disk_free_bytes: number;
  disk_total_bytes: number;
  database_bytes: number;
  default_credentials: boolean;
  workers: WorkerStatus[];
  cloud: {
    enabled: boolean;
    url: string;
    last_ok_at: number | null;
    last_error: string | null;
    last_error_at: number | null;
    commands_applied: number;
  } | null;
}

export interface LogEntry {
  id: number;
  time: number;
  level: string;
  logger: string;
  message: string;
}

export type VictronKind = "battery_monitor" | "solar_charger" | "dcdc_converter" | "inverter_charger";

export interface VictronConfigured {
  name: string;
  mac: string;
  source: "dashboard" | "env";
  kind: string | null;
  model: string | null;
  rssi: number | null;
  updated_at: number | null;
  status: "ok" | "stale" | "never";
}

export interface VictronNearby {
  mac: string;
  name: string | null;
  kind: string | null;
  rssi: number | null;
  seen_at: number;
  added_as: string | null;
  suggested_name: string;
}

export interface VictronDevicesResponse {
  bluetooth: boolean;
  error: string | null;
  devices: VictronConfigured[];
}
