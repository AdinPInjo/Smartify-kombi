// Custom dashboards (Overview, tablet panel): which cards, in what order, how
// wide and how tall. Stored per browser, so the phone and the wall tablet differ.
//
// The grid has 6 columns: width 2 = a third, 3 = half, 4 = two thirds, 6 = full.
// Height is 1 or 2 rows. On a phone the grid has 2 columns: a third or half
// becomes half, anything wider becomes full.

import { useCallback, useState } from "react";

export type CardWidth = 2 | 3 | 4 | 6;
export type CardHeight = 1 | 2;

export const WIDTHS: { value: CardWidth; label: string; name: string }[] = [
  { value: 2, label: "⅓", name: "a third" },
  { value: 3, label: "½", name: "half" },
  { value: 4, label: "⅔", name: "two thirds" },
  { value: 6, label: "1", name: "full width" },
];

export interface CardLayout<Id extends string = string> {
  id: Id;
  w: CardWidth;
  h: CardHeight;
  hidden: boolean;
}

export interface DashLayout<Id extends string = string> {
  cards: CardLayout<Id>[];
}

export interface DashDefinition<Id extends string> {
  /** localStorage key. */
  key: string;
  /** Every card, in the default order, with its default size. */
  cards: { id: Id; label: string; w: CardWidth; h: CardHeight; hidden?: boolean }[];
  /** Read an older stored format, if there is one. */
  migrate?: () => DashLayout<Id> | null;
}

const isWidth = (w: unknown): w is CardWidth => w === 2 || w === 3 || w === 4 || w === 6;

export function defaultLayout<Id extends string>(def: DashDefinition<Id>): DashLayout<Id> {
  return { cards: def.cards.map(({ id, w, h, hidden }) => ({ id, w, h, hidden: hidden ?? false })) };
}

/** Keep what is valid, add cards from newer versions at the end. */
export function normalize<Id extends string>(def: DashDefinition<Id>, raw: unknown): DashLayout<Id> {
  const known = new Map(def.cards.map((c) => [c.id as string, c]));
  const cards: CardLayout<Id>[] = [];
  const list = (raw as { cards?: unknown })?.cards;
  if (Array.isArray(list)) {
    for (const item of list as Partial<CardLayout>[]) {
      const base = item && known.get(String(item.id));
      if (!base || cards.some((c) => c.id === base.id)) continue;
      cards.push({ id: base.id, w: isWidth(item.w) ? item.w : base.w, h: item.h === 2 ? 2 : 1, hidden: item.hidden === true });
    }
  }
  for (const card of defaultLayout(def).cards) if (!cards.some((c) => c.id === card.id)) cards.push(card);
  return { cards };
}

function load<Id extends string>(def: DashDefinition<Id>): DashLayout<Id> {
  try {
    const raw = window.localStorage.getItem(def.key);
    if (raw) return normalize(def, JSON.parse(raw));
    const migrated = def.migrate?.();
    if (migrated) return normalize(def, migrated);
  } catch {
    /* unreadable: start from the default */
  }
  return defaultLayout(def);
}

/** Move a card to where another one is (drag and drop). */
export function moveTo<Id extends string>(layout: DashLayout<Id>, id: Id, target: Id): DashLayout<Id> {
  const cards = [...layout.cards];
  const from = cards.findIndex((c) => c.id === id);
  const to = cards.findIndex((c) => c.id === target);
  if (from < 0 || to < 0 || from === to) return layout;
  const [card] = cards.splice(from, 1);
  cards.splice(to, 0, card);
  return { cards };
}

/** Move a card one place earlier (-1) or later (+1) among the visible cards. */
export function step<Id extends string>(layout: DashLayout<Id>, id: Id, direction: -1 | 1): DashLayout<Id> {
  const visible = layout.cards.filter((c) => !c.hidden);
  const neighbour = visible[visible.findIndex((c) => c.id === id) + direction];
  return neighbour ? moveTo(layout, id, neighbour.id) : layout;
}

export function change<Id extends string>(
  layout: DashLayout<Id>,
  id: Id,
  values: Partial<Omit<CardLayout<Id>, "id">>,
): DashLayout<Id> {
  return { cards: layout.cards.map((c) => (c.id === id ? { ...c, ...values } : c)) };
}

export function useDashLayout<Id extends string>(def: DashDefinition<Id>) {
  const [layout, setLayout] = useState<DashLayout<Id>>(() => load(def));
  const save = useCallback(
    (next: DashLayout<Id>) => {
      setLayout(next);
      try {
        window.localStorage.setItem(def.key, JSON.stringify(next));
      } catch {
        /* private mode: keep it for this session only */
      }
    },
    [def.key],
  );
  const reset = useCallback(() => save(defaultLayout(def)), [save, def]);
  return { layout, save, reset };
}
