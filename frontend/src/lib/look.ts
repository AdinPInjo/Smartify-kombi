// How the dashboard looks, chosen per device in Settings → Look:
// dark (default), light, or auto (follows the phone), and colored cards.
// Applied as data attributes on <html>; styles.css does the rest.

import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light" | "auto";
export interface Look {
  theme: Theme;
  colorful: boolean;
}

const KEY = "smartify.look";
const DEFAULT: Look = { theme: "dark", colorful: true };

export function loadLook(): Look {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) {
      const look = JSON.parse(raw) as Partial<Look>;
      return {
        theme: look.theme === "light" || look.theme === "auto" ? look.theme : "dark",
        colorful: look.colorful !== false,
      };
    }
  } catch {
    /* default */
  }
  return DEFAULT;
}

const prefersLight = () => window.matchMedia?.("(prefers-color-scheme: light)").matches ?? false;

export function applyLook(look: Look = loadLook()) {
  const root = document.documentElement;
  const light = look.theme === "light" || (look.theme === "auto" && prefersLight());
  root.dataset.theme = light ? "light" : "dark";
  root.dataset.cards = look.colorful ? "color" : "plain";
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", light ? "#f4f1e8" : "#11130e");
}

/** Follow the phone's light/dark setting while "auto" is chosen. */
export function watchSystemTheme() {
  window.matchMedia?.("(prefers-color-scheme: light)").addEventListener?.("change", () => applyLook());
}

export function useLook() {
  const [look, setLook] = useState<Look>(loadLook);
  useEffect(() => applyLook(look), [look]);
  const save = useCallback((next: Look) => {
    setLook(next);
    try {
      window.localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      /* this visit only */
    }
  }, []);
  return { look, save };
}
