import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const API_BASE = import.meta.env.VITE_SMARTIFY_API_BASE || "";
const API_KEY = import.meta.env.VITE_SMARTIFY_API_KEY as string | undefined;

/**
 * Wrapper around fetch that automatically:
 * - prefixes relative URLs with VITE_SMARTIFY_API_BASE (if set)
 * - sends X-API-Key header when VITE_SMARTIFY_API_KEY is defined
 * - defaults credentials to "include" (cookies) unless overridden
 */
export function apiFetch(input: string, init: RequestInit = {}) {
  const url = input.startsWith("http://") || input.startsWith("https://") ? input : `${API_BASE}${input}`;

  const headers = new Headers(init.headers || {});
  if (API_KEY) {
    headers.set("X-API-Key", API_KEY);
  }

  const finalInit: RequestInit = {
    ...init,
    headers,
    credentials: init.credentials ?? "include",
  };

  // Log in dev mode to help debug
  if (import.meta.env.DEV) {
    console.log(`[apiFetch] ${init.method || 'GET'} ${url}`, { hasApiKey: !!API_KEY, credentials: finalInit.credentials });
  }

  return fetch(url, finalInit).catch((err) => {
    console.error(`[apiFetch] Failed to fetch ${url}:`, err);
    throw err;
  });
}

