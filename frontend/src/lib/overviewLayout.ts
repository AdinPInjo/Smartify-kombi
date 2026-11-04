// The Overview's cards (see dashLayout.ts for how layouts work).

import { useDashLayout, type DashDefinition, type DashLayout } from "./dashLayout";

export type OverviewCardId = "climate" | "heater" | "weather" | "battery" | "water" | "charging" | "scenes" | "switches" | "map";

export const OVERVIEW: DashDefinition<OverviewCardId> = {
  key: "smartify.overview.v3",
  cards: [
    { id: "climate", label: "Cabin climate", w: 4, h: 1 },
    // Hidden until a heater is added (its setup offers to show it).
    { id: "heater", label: "Diesel heater", w: 3, h: 1, hidden: true },
    { id: "weather", label: "Weather", w: 2, h: 1 },
    { id: "battery", label: "Battery", w: 2, h: 1 },
    { id: "water", label: "Fresh water", w: 2, h: 1 },
    { id: "charging", label: "Charging", w: 2, h: 1 },
    { id: "scenes", label: "Scenes", w: 6, h: 1 },
    { id: "switches", label: "Switches", w: 6, h: 1 },
    { id: "map", label: "Map", w: 6, h: 1 },
  ],
  // Before 0.5.0: only an order and hidden cards.
  migrate: () => {
    const raw = window.localStorage.getItem("smartify.overview.v2");
    if (!raw) return null;
    const old = JSON.parse(raw) as { order?: string[]; hidden?: string[] };
    return {
      cards: (old.order ?? []).map((id) => ({ id, hidden: (old.hidden ?? []).includes(id) })),
    } as unknown as DashLayout<OverviewCardId>;
  },
};

export const useOverviewLayout = () => useDashLayout(OVERVIEW);
