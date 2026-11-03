// The Overview as a custom dashboard: which cards, in what order, how wide and
// how tall. Stored per browser, so the phone and the wall tablet can differ.
//
// The grid has 6 columns: width 2 = a third, 3 = half, 4 = two thirds, 6 = full.
// Height is 1 or 2 rows. On a phone the grid has 2 columns: a third or half
// becomes half, anything wider becomes full.

import { useCallback, useState } from "react";

export const OVERVIEW_CARDS = [
  { id: "climate", label: "Cabin climate" },
  { id: "battery", label: "Battery" },
  { id: "water", label: "Fresh water" },
  { id: "charging", label: "Charging" },
  { id: "switches", label: "Switches" },
  { id: "map", label: "Map" },
] as const;

export type OverviewCardId = (typeof OVERVIEW_CARDS)[number]["id"];
export type CardWidth = 2 | 3 | 4 | 6;
export type CardHeight = 1 | 2;

export const WIDTHS: { value: CardWidth; label: string; name: string }[] = [
  { value: 2, label: "⅓", name: "a third" },
  { value: 3, label: "½", name: "half" },
  { value: 4, label: "⅔", name: "two thirds" },
  { value: 6, label: "1", name: "full width" },
];

export interface CardLayout {
  id: OverviewCardId;
  w: CardWidth;
  h: CardHeight;
  hidden: boolean;
}

export interface OverviewLayout {
  cards: CardLayout[];
}

const KEY = "smartify.overview.v3";
const OLD_KEY = "smartify.overview.v2";

const DEFAULT_SIZE: Record<OverviewCardId, { w: CardWidth; h: CardHeight }> = {
  climate: { w: 4, h: 1 },
  battery: { w: 2, h: 1 },
  water: { w: 2, h: 1 },
  charging: { w: 4, h: 1 },
  switches: { w: 6, h: 1 },
  map: { w: 6, h: 1 },
};

export const DEFAULT_LAYOUT: OverviewLayout = {
  cards: OVERVIEW_CARDS.map(({ id }) => ({ id, ...DEFAULT_SIZE[id], hidden: false })),
};

const isWidth = (w: unknown): w is CardWidth => w === 2 || w === 3 || w === 4 || w === 6;

/** Keep what is valid, add cards from newer versions at the end. */
export function normalize(raw: unknown): OverviewLayout {
  const known = new Set<string>(OVERVIEW_CARDS.map((c) => c.id));
  const cards: CardLayout[] = [];
  const list = (raw as { cards?: unknown })?.cards;
  if (Array.isArray(list)) {
    for (const item of list as Partial<CardLayout>[]) {
      if (!item || !known.has(String(item.id)) || cards.some((c) => c.id === item.id)) continue;
      const id = item.id as OverviewCardId;
      cards.push({
        id,
        w: isWidth(item.w) ? item.w : DEFAULT_SIZE[id].w,
        h: item.h === 2 ? 2 : 1,
        hidden: item.hidden === true,
      });
    }
  }
  for (const card of DEFAULT_LAYOUT.cards) if (!cards.some((c) => c.id === card.id)) cards.push({ ...card });
  return { cards };
}

/** The previous format (order + hidden), so nobody loses their arrangement. */
function fromOldFormat(raw: string): OverviewLayout {
  const old = JSON.parse(raw) as { order?: string[]; hidden?: string[] };
  return normalize({
    cards: (old.order ?? []).map((id) => ({
      id,
      ...DEFAULT_SIZE[id as OverviewCardId],
      hidden: (old.hidden ?? []).includes(id),
    })),
  });
}

function load(): OverviewLayout {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) return normalize(JSON.parse(raw));
    const old = window.localStorage.getItem(OLD_KEY);
    if (old) return fromOldFormat(old);
  } catch {
    /* unreadable: start from the default */
  }
  return DEFAULT_LAYOUT;
}

/** Move a card to where another one is (drag and drop). */
export function moveTo(layout: OverviewLayout, id: OverviewCardId, target: OverviewCardId): OverviewLayout {
  const cards = [...layout.cards];
  const from = cards.findIndex((c) => c.id === id);
  const to = cards.findIndex((c) => c.id === target);
  if (from < 0 || to < 0 || from === to) return layout;
  const [card] = cards.splice(from, 1);
  cards.splice(to, 0, card);
  return { cards };
}

/** Move a card one place earlier (-1) or later (+1) among the visible cards. */
export function step(layout: OverviewLayout, id: OverviewCardId, direction: -1 | 1): OverviewLayout {
  const visible = layout.cards.filter((c) => !c.hidden);
  const index = visible.findIndex((c) => c.id === id);
  const neighbour = visible[index + direction];
  return neighbour ? moveTo(layout, id, neighbour.id) : layout;
}

export function change(layout: OverviewLayout, id: OverviewCardId, values: Partial<Omit<CardLayout, "id">>): OverviewLayout {
  return { cards: layout.cards.map((c) => (c.id === id ? { ...c, ...values } : c)) };
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
  const reset = useCallback(() => save(DEFAULT_LAYOUT), [save]);
  return { layout, save, reset };
}
