export type OverviewModuleId =
  | "gps_card"
  | "temp_card"
  | "weather_card"
  | "water_card"
  | "battery"
  | "header_relay"
  | "relay_rules"
  | "gps_map";

export type OverviewLayoutConfig = {
  topOrder: OverviewModuleId[];
  bottomOrder: OverviewModuleId[];
  hidden: OverviewModuleId[];
  columns?: 3 | 4 | 5;
};

export const OVERVIEW_MODULES: { id: OverviewModuleId; label: string; zone: "top" | "bottom" }[] = [
  { id: "gps_card", label: "GPS Location (Mini)", zone: "top" },
  { id: "temp_card", label: "Temperature", zone: "top" },
  { id: "weather_card", label: "Weather Forecast", zone: "top" },
  { id: "water_card", label: "Water Level", zone: "top" },
  { id: "battery", label: "Battery", zone: "top" },
  { id: "header_relay", label: "Header Relay", zone: "top" },
  { id: "relay_rules", label: "Relay Rules", zone: "top" },
  { id: "gps_map", label: "GPS Map & Track", zone: "bottom" },
];

export const DEFAULT_OVERVIEW_LAYOUT: OverviewLayoutConfig = {
  topOrder: ["gps_card", "temp_card", "weather_card", "water_card", "battery", "header_relay", "relay_rules"],
  bottomOrder: ["gps_map"],
  hidden: [],
  columns: 3,
};

const STORAGE_KEY = "smartify_overview_layout_v1";

const normalize = (config: OverviewLayoutConfig): OverviewLayoutConfig => {
  const validIds = new Set(OVERVIEW_MODULES.map((m) => m.id));
  const uniq = (list: OverviewModuleId[]) => Array.from(new Set(list.filter((id) => validIds.has(id))));

  const topOrder = uniq(config.topOrder);
  const bottomOrder = uniq(config.bottomOrder);
  const hidden = uniq(config.hidden);

  const ensureAll = (target: OverviewModuleId[], zone: "top" | "bottom") => {
    for (const mod of OVERVIEW_MODULES) {
      if (mod.zone !== zone) continue;
      if (!target.includes(mod.id) && !bottomOrder.includes(mod.id) && !topOrder.includes(mod.id)) {
        target.push(mod.id);
      }
    }
  };

  ensureAll(topOrder, "top");
  ensureAll(bottomOrder, "bottom");

  const columns = config.columns === 5 ? 5 : config.columns === 4 ? 4 : 3;
  return { topOrder, bottomOrder, hidden, columns };
};

export const getOverviewLayout = (): OverviewLayoutConfig => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_OVERVIEW_LAYOUT;
    const parsed = JSON.parse(raw) as OverviewLayoutConfig;
    return normalize(parsed);
  } catch {
    return DEFAULT_OVERVIEW_LAYOUT;
  }
};

export const setOverviewLayout = (config: OverviewLayoutConfig) => {
  const normalized = normalize(config);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  window.dispatchEvent(new Event("overview-layout-change"));
};

export const resetOverviewLayout = () => {
  setOverviewLayout(DEFAULT_OVERVIEW_LAYOUT);
};
