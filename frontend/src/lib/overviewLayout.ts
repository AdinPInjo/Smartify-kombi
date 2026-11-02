// Which cards the Overview shows, and in what order. Stored per browser, so the
// phone and the tablet can each have their own layout.

import { useCallback, useState } from "react";

export const OVERVIEW_CARDS = [
  { id: "climate", label: "Cabin climate" },
  { id: "battery", label: "Battery" },
  { id: "water", label: "Fresh water" },
  { id: "charging", label: "Charging (solar, alternator, inverter)" },
  { id: "switches", label: "Switches" },
  { id: "map", label: "Map" },
] as const;

export type OverviewCardId = (typeof OVERVIEW_CARDS)[number]["id"];

export interface OverviewLayout {
  order: OverviewCardId[];
  hidden: OverviewCardId[];
}

const KEY = "smartify.overview.v2";
const DEFAULT: OverviewLayout = { order: OVERVIEW_CARDS.map((c) => c.id), hidden: [] };

function load(): OverviewLayout {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return DEFAULT;
    const parsed = JSON.parse(raw) as OverviewLayout;
    const known = new Set<string>(DEFAULT.order);
    const order = parsed.order.filter((id) => known.has(id));
    // Cards added in a newer version appear at the end.
    for (const id of DEFAULT.order) if (!order.includes(id)) order.push(id);
    return { order, hidden: parsed.hidden.filter((id) => known.has(id)) };
  } catch {
    return DEFAULT;
  }
}

export function useOverviewLayout() {
  const [layout, setLayout] = useState<OverviewLayout>(load);
  const save = useCallback((next: OverviewLayout) => {
    setLayout(next);
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* private mode: keep it for this session only */
    }
  }, []);
  const reset = useCallback(() => save(DEFAULT), [save]);
  return { layout, save, reset };
}
