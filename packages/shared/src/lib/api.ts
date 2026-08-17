import { useAuth } from "@/store/auth";

const DEFAULT_ORIGIN = (import.meta as any).env?.VITE_API_URL || "http://localhost:8000";

// Server manzili — foydalanuvchi sozlaydi (localStorage), bitta .exe istalgan serverga ulanadi.
export function getServerUrl(): string {
  try {
    const u = localStorage.getItem("savdoos_api_url");
    if (u) return u;
  } catch {
    /* ignore */
  }
  return DEFAULT_ORIGIN;
}

export function setServerUrl(url: string): void {
  try {
    localStorage.setItem("savdoos_api_url", url.trim().replace(/\/+$/, ""));
  } catch {
    /* ignore */
  }
}

function base(): string {
  return getServerUrl().replace(/\/+$/, "") + "/api/v1";
}

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = useAuth.getState().token;
  const res = await fetch(base() + path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.headers || {}),
    },
  });
  if (res.status === 401) {
    useAuth.getState().logout();
    throw new Error("Sessiya tugadi — qayta kiring");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null as T;
  return res.json();
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body: unknown) =>
  api<T>(p, { method: "POST", body: JSON.stringify(body) });
export const put = <T = any>(p: string, body: unknown) =>
  api<T>(p, { method: "PUT", body: JSON.stringify(body) });
