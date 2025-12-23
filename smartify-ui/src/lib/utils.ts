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
  // Otherwise, prefix with API_BASE if set (empty string = use relative URL)
  // When frontend and backend are on same origin, API_BASE should be empty
  const url = input.startsWith("http://") || input.startsWith("https://") 
    ? input 
    : (API_BASE ? `${API_BASE}${input}` : input);

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

  return fetch(url, finalInit)
    .then((response) => {
      // Log response status for debugging
      if (import.meta.env.DEV && !response.ok) {
        console.warn(`[apiFetch] ${url} returned status ${response.status}`);
      }
      return response;
    })
    .catch((err) => {
      // More detailed error logging
      console.error(`[apiFetch] Failed to fetch ${url}:`, {
        error: err,
        message: err.message,
        name: err.name,
        stack: err.stack,
        url,
        apiBase: API_BASE,
        hasApiKey: !!API_KEY,
      });
      throw err;
    });
}

