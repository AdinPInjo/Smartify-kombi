import { BASE_PATH } from "@/lib/base";

// Thin fetch wrapper. All requests go to the same origin as the dashboard
// (the backend serves it), or through Vite's dev proxy.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// "/api" on the van, "/kombi/api" for a remote dashboard in a subfolder.
const BASE = import.meta.env.VITE_API_BASE ?? BASE_PATH.replace(/\/$/, "");

let onUnauthorized: (() => void) | null = null;

/** Called once by the auth provider: any 401 sends the user to the login page. */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}/api${path}`, {
    method,
    credentials: "include",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 401 && !path.startsWith("/auth/")) {
    onUnauthorized?.();
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) {
        message = data.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ");
      }
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, message || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
  url: (path: string) => `${BASE}/api${path}`,
};
