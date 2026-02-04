export type OverviewModuleId =
  | "gps_card"
  | "temp_water"
  | "battery"
  | "header_relay"
  | "relay_rules"
  | "gps_map";

export type OverviewLayoutConfig = {
  topOrder: OverviewModuleId[];
  bottomOrder: OverviewModuleId[];
  hidden: OverviewModuleId[];
};

export const OVERVIEW_MODULES: { id: OverviewModuleId; label: string; zone: "top" | "bottom" }[] = [
  { id: "gps_card", label: "GPS Location (Mini)", zone: "top" },
  { id: "temp_water", label: "Temperature + Water", zone: "top" },
  { id: "battery", label: "Battery", zone: "top" },
  { id: "header_relay", label: "Header Relay", zone: "top" },
  { id: "relay_rules", label: "Relay Rules", zone: "bottom" },
  { id: "gps_map", label: "GPS Map & Track", zone: "bottom" },
];

export const DEFAULT_OVERVIEW_LAYOUT: OverviewLayoutConfig = {
  topOrder: ["gps_card", "temp_water", "battery", "header_relay"],
  bottomOrder: ["relay_rules", "gps_map"],
  hidden: [],
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

  return { topOrder, bottomOrder, hidden };
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
