import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

/**
 * Centralized API client that wraps fetch and automatically:
 * - Prefixes relative URLs with VITE_API_BASE_URL (if set)
 * - Sends X-API-Key header when VITE_API_KEY is defined
 * - Defaults credentials to "include" (cookies) unless overridden
 * 
 * All API requests should use this function instead of direct fetch() calls.
 */
export function apiFetch(input: string, init: RequestInit = {}) {
  // If URL is already absolute (starts with http:// or https://), use it as-is
  // Otherwise, prefix with API_BASE if set
  const url = input.startsWith("http://") || input.startsWith("https://") 
    ? input 
    : `${API_BASE}${input}`;

  const headers = new Headers(init.headers || {});
  
  // Always include X-API-Key header if API_KEY is defined
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
    console.log(`[apiFetch] ${init.method || 'GET'} ${url}`, { 
      hasApiKey: !!API_KEY, 
      credentials: finalInit.credentials,
      apiBase: API_BASE || '(none, using relative URLs)'
    });
  }

  return fetch(url, finalInit).catch((err) => {
    console.error(`[apiFetch] Failed to fetch ${url}:`, err);
    throw err;
  });
}

